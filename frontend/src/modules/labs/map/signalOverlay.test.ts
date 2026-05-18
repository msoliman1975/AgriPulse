import { describe, expect, it } from "vitest";
import type { FeatureCollection, Polygon } from "geojson";

import type { SignalObservation } from "@/api/signals";

import {
  blockCentroidsFromGeojson,
  buildSignalOverlay,
  formatObservationValue,
} from "./signalOverlay";
import type { UnitFeatureProps } from "./types";

function _obs(overrides: Partial<SignalObservation>): SignalObservation {
  return {
    id: "obs-1",
    time: "2026-05-18T08:00:00+00:00",
    signal_definition_id: "def-1",
    signal_code: "soil_ph",
    farm_id: "farm-1",
    block_id: null,
    value_numeric: null,
    value_categorical: null,
    value_event: null,
    value_boolean: null,
    value_geopoint: null,
    attachment_s3_key: null,
    attachment_download_url: null,
    notes: null,
    recorded_by: "user-1",
    inserted_at: "2026-05-18T08:00:00+00:00",
    ...overrides,
  };
}

describe("formatObservationValue", () => {
  it("renders numeric as the raw Decimal string", () => {
    expect(formatObservationValue(_obs({ value_numeric: "6.7" }))).toBe("6.7");
  });

  it("renders categorical", () => {
    expect(formatObservationValue(_obs({ value_categorical: "high" }))).toBe("high");
  });

  it("renders event", () => {
    expect(formatObservationValue(_obs({ value_event: "harvest_started" }))).toBe(
      "harvest_started",
    );
  });

  it.each([
    [true, "Yes"],
    [false, "No"],
  ])("renders boolean %s as %s", (input, expected) => {
    expect(formatObservationValue(_obs({ value_boolean: input }))).toBe(expected);
  });

  it("renders geopoint as lat,lon with 5 decimals", () => {
    expect(
      formatObservationValue(
        _obs({ value_geopoint: { latitude: 30.123456, longitude: 31.789012 } }),
      ),
    ).toBe("30.12346, 31.78901");
  });

  it("renders em-dash for an empty observation", () => {
    expect(formatObservationValue(_obs({}))).toBe("—");
  });
});

describe("buildSignalOverlay", () => {
  it("uses location_point when present (precision over fallback)", () => {
    const result = buildSignalOverlay(
      [
        _obs({
          value_numeric: "1",
          location_mode: "free_point",
          location_point: { latitude: 30.5, longitude: 31.0 },
          block_id: "block-1",
        }),
      ],
      new Map([["block-1", [99, 99]]]),
    );
    expect(result.features.features).toHaveLength(1);
    const f = result.features.features[0];
    expect(f.geometry.coordinates).toEqual([31.0, 30.5]);
    expect(f.properties.source).toBe("location_point");
    expect(result.skippedCount).toBe(0);
  });

  it("falls back to value_geopoint when location_point missing", () => {
    const result = buildSignalOverlay(
      [_obs({ value_geopoint: { latitude: 30.5, longitude: 31.0 }, block_id: "block-1" })],
      new Map([["block-1", [99, 99]]]),
    );
    const f = result.features.features[0];
    expect(f.geometry.coordinates).toEqual([31.0, 30.5]);
    expect(f.properties.source).toBe("value_geopoint");
  });

  it("falls back to block centroid for entity-mode observations", () => {
    const result = buildSignalOverlay(
      [_obs({ value_numeric: "6.7", block_id: "block-1", location_mode: "entity" })],
      new Map([["block-1", [31.0, 30.5]]]),
    );
    const f = result.features.features[0];
    expect(f.geometry.coordinates).toEqual([31.0, 30.5]);
    expect(f.properties.source).toBe("block_centroid");
  });

  it("skips observations with no resolvable coord", () => {
    // entity mode + missing block_id ⇒ nowhere to place.
    const result = buildSignalOverlay(
      [_obs({ value_numeric: "1", location_mode: "entity", block_id: null })],
      new Map(),
    );
    expect(result.features.features).toHaveLength(0);
    expect(result.skippedCount).toBe(1);
  });

  it("rejects geopoints with out-of-range coordinates", () => {
    const result = buildSignalOverlay(
      [
        _obs({
          value_numeric: "1",
          // intentionally insane — lat 200, lon NaN
          location_point: { latitude: 200, longitude: Number.NaN },
          block_id: "block-1",
        }),
      ],
      new Map([["block-1", [31.0, 30.5]]]),
    );
    // location_point rejected ⇒ falls through to centroid.
    expect(result.features.features[0].properties.source).toBe("block_centroid");
  });

  it("includes value_kind from options on every feature", () => {
    const result = buildSignalOverlay(
      [_obs({ value_numeric: "1", block_id: "block-1" })],
      new Map([["block-1", [0, 0]]]),
      { valueKind: "numeric" },
    );
    expect(result.features.features[0].properties.value_kind).toBe("numeric");
  });
});

describe("blockCentroidsFromGeojson", () => {
  it("averages the polygon vertices, skipping the closing duplicate", () => {
    const fc: FeatureCollection<Polygon, UnitFeatureProps> = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { id: "block-1" } as UnitFeatureProps,
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
                [0, 0],
              ],
            ],
          },
        },
      ],
    };
    const out = blockCentroidsFromGeojson(fc);
    expect(out.get("block-1")).toEqual([5, 5]);
  });

  it("skips features without an id", () => {
    const fc: FeatureCollection<Polygon, UnitFeatureProps> = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { id: "" } as UnitFeatureProps,
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 0],
              ],
            ],
          },
        },
      ],
    };
    expect(blockCentroidsFromGeojson(fc).size).toBe(0);
  });

  it("skips degenerate polygons", () => {
    const fc: FeatureCollection<Polygon, UnitFeatureProps> = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { id: "block-x" } as UnitFeatureProps,
          geometry: { type: "Polygon", coordinates: [[]] },
        },
      ],
    };
    expect(blockCentroidsFromGeojson(fc).size).toBe(0);
  });
});
