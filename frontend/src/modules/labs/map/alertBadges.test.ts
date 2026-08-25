import { describe, expect, it } from "vitest";
import type { FeatureCollection, Polygon } from "geojson";

import { buildAlertBadgePoints } from "./alertBadges";
import type { UnitFeatureProps } from "./types";

function props(over: Partial<UnitFeatureProps> = {}): UnitFeatureProps {
  return {
    id: "b1",
    type: "block",
    parent_pivot_id: null,
    is_logical_pivot: false,
    name: "B1",
    health: "healthy",
    has_alert: false,
    alert_severity: "none",
    alert_count: 0,
    alert_action_type: null,
    is_future: false,
    risk_level: "none",
    ...over,
  };
}

// A plain square, and an L-shape whose centroid falls in the notch —
// the case that makes `pointOnFeature` the right tool rather than a
// centroid.
const SQUARE: Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [2, 0],
      [2, 2],
      [0, 2],
      [0, 0],
    ],
  ],
};

const L_SHAPE: Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [6, 0],
      [6, 2],
      [2, 2],
      [2, 6],
      [0, 6],
      [0, 0],
    ],
  ],
};

function fc(
  features: { geometry: Polygon; properties: UnitFeatureProps; id: string }[],
): FeatureCollection<Polygon, UnitFeatureProps> {
  return {
    type: "FeatureCollection",
    features: features.map((f) => ({
      type: "Feature",
      id: f.id,
      geometry: f.geometry,
      properties: f.properties,
    })),
  };
}

describe("buildAlertBadgePoints", () => {
  it("emits ONE point per alerting block, not one per vertex", () => {
    // The regression. The square has 5 coordinates (4 corners + closing
    // point); bound straight to a circle layer that painted 4 badges.
    const out = buildAlertBadgePoints(
      fc([{ id: "b1", geometry: SQUARE, properties: props({ has_alert: true }) }]),
    );

    expect(out.features).toHaveLength(1);
    expect(out.features[0].geometry.type).toBe("Point");
    expect(SQUARE.coordinates[0]).toHaveLength(5);
  });

  it("drops blocks with no alert", () => {
    const out = buildAlertBadgePoints(
      fc([
        { id: "b1", geometry: SQUARE, properties: props({ has_alert: true }) },
        { id: "b2", geometry: SQUARE, properties: props({ id: "b2", has_alert: false }) },
      ]),
    );

    expect(out.features.map((f) => f.id)).toEqual(["b1"]);
  });

  it("is empty when the farm is healthy", () => {
    const out = buildAlertBadgePoints(fc([{ id: "b1", geometry: SQUARE, properties: props() }]));

    expect(out.features).toEqual([]);
  });

  it("carries severity through so the layer can colour by it", () => {
    const out = buildAlertBadgePoints(
      fc([
        {
          id: "b1",
          geometry: SQUARE,
          properties: props({ has_alert: true, alert_severity: "critical" }),
        },
      ]),
    );

    expect(out.features[0].properties.alert_severity).toBe("critical");
  });

  it("resolves the marker image from the verb and the severity", () => {
    const out = buildAlertBadgePoints(
      fc([
        {
          id: "b1",
          geometry: SQUARE,
          properties: props({
            has_alert: true,
            alert_count: 3,
            alert_severity: "critical",
            alert_action_type: "irrigate",
          }),
        },
      ]),
    );

    expect(out.features[0].properties.marker_icon).toBe("ap-alert-irrigate-critical");
    expect(out.features[0].properties.marker_count).toBe("3");
  });

  it("falls back to the neutral glyph for a verb we have no artwork for", () => {
    // MapLibre draws NOTHING for an unresolvable icon-image and reports no
    // error, so a verb the backend grows later must not reach the layer as
    // an id nobody registered — the alert would vanish off the map.
    const out = buildAlertBadgePoints(
      fc([
        {
          id: "b1",
          geometry: SQUARE,
          properties: props({
            has_alert: true,
            alert_severity: "watch",
            alert_action_type: "mulch",
          }),
        },
        {
          id: "b2",
          geometry: SQUARE,
          properties: props({ id: "b2", has_alert: true, alert_action_type: null }),
        },
      ]),
    );

    expect(out.features[0].properties.marker_icon).toBe("ap-alert-unknown-watch");
    expect(out.features[1].properties.marker_icon).toBe("ap-alert-unknown-ok");
  });

  it("caps the count so one bad block cannot draw a chip wider than the farm", () => {
    const out = buildAlertBadgePoints(
      fc([
        {
          id: "b1",
          geometry: SQUARE,
          properties: props({ has_alert: true, alert_count: 240 }),
        },
      ]),
    );

    expect(out.features[0].properties.marker_count).toBe("99+");
  });

  it("anchors inside a concave block rather than in its notch", () => {
    // The L's centroid sits around (1.8, 1.8) — outside the polygon, over
    // whatever block occupies the notch. The badge must not go there.
    const out = buildAlertBadgePoints(
      fc([{ id: "b1", geometry: L_SHAPE, properties: props({ has_alert: true }) }]),
    );
    const [x, y] = out.features[0].geometry.coordinates;

    const inNotch = x > 2 && y > 2;
    expect(inNotch).toBe(false);
  });
});
