import { describe, expect, it } from "vitest";

import type { FieldFlag } from "@/api/fieldFlags";

import { buildFlagOverlay } from "./flagOverlay";

function flag(over: Partial<FieldFlag> = {}): FieldFlag {
  return {
    id: "fl1",
    farm_id: "f1",
    block_id: "b1",
    block_name: "Block 1",
    block_name_ar: null,
    note: "Main line cracked near the pump shed\nsecond line",
    severity: "warning",
    status: "open",
    point: null,
    accuracy_m: null,
    pin_until: "2026-09-01T00:00:00Z",
    is_pinned: true,
    raised_by: "u1",
    raised_by_name: "Ahmed",
    raised_by_name_ar: null,
    closed_at: null,
    closed_by: null,
    closed_by_name: null,
    closed_by_name_ar: null,
    close_reason: null,
    comment_count: 0,
    photos: [],
    comments: [],
    created_at: "2026-08-19T00:00:00Z",
    updated_at: "2026-08-19T00:00:00Z",
    ...over,
  };
}

const CENTROIDS = new Map<string, [number, number]>([["b1", [31.44, 30.11]]]);

describe("buildFlagOverlay", () => {
  it("puts the pin where the scout stood when there is a position", () => {
    const fc = buildFlagOverlay(
      [flag({ point: { type: "Point", coordinates: [31.5, 30.2] } })],
      CENTROIDS,
    );
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].geometry.coordinates).toEqual([31.5, 30.2]);
    expect(fc.features[0].properties.source).toBe("point");
  });

  it("falls back to the block centroid rather than dropping the flag", () => {
    // Most flags have no position: the old app never sent one, and a scout can
    // refuse the permission. A finding with no coordinate is still a finding.
    const fc = buildFlagOverlay([flag()], CENTROIDS);
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].geometry.coordinates).toEqual([31.44, 30.11]);
    expect(fc.features[0].properties.source).toBe("block_centroid");
  });

  it("omits a flag it cannot place, rather than drawing it at null island", () => {
    const fc = buildFlagOverlay([flag({ block_id: "unknown" })], CENTROIDS);
    expect(fc.features).toEqual([]);
  });

  it("carries open state so the layer can draw closed pins hollow", () => {
    const fc = buildFlagOverlay(
      [flag({ status: "closed" }), flag({ id: "fl2", status: "open" })],
      CENTROIDS,
    );
    expect(fc.features.map((f) => f.properties.open)).toEqual([false, true]);
  });

  it("titles a pin with the first line only", () => {
    const fc = buildFlagOverlay([flag()], CENTROIDS);
    expect(fc.features[0].properties.title).toBe("Main line cracked near the pump shed");
  });

  it("ignores a non-finite coordinate instead of trusting it", () => {
    const fc = buildFlagOverlay(
      [flag({ point: { type: "Point", coordinates: [Number.NaN, 30.2] } })],
      CENTROIDS,
    );
    expect(fc.features[0].properties.source).toBe("block_centroid");
  });
});
