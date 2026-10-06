import { describe, expect, it } from "vitest";

import { DRAW_STYLES } from "./drawStyles";

describe("DRAW_STYLES", () => {
  it("wraps every dash array in a literal, which MapLibre needs", () => {
    // A bare array here is read as an expression and the whole layer is
    // dropped: the edges of a shape being drawn then never appear.
    for (const layer of DRAW_STYLES as { id: string; paint?: Record<string, unknown> }[]) {
      const dash = layer.paint?.["line-dasharray"];
      if (dash === undefined) continue;
      expect(Array.isArray(dash) && dash[0], layer.id).toBe("literal");
    }
  });

  it("styles the active polygon edge, which the trash button selects", () => {
    const ids = (DRAW_STYLES as { id: string }[]).map((l) => l.id);
    expect(ids).toContain("gl-draw-polygon-stroke-active");
    expect(ids).toContain("gl-draw-polygon-and-line-vertex-inactive");
  });
});

describe("applyMapLibreClassesToDraw", () => {
  it("renames Draw's control classes to MapLibre's, so its buttons take clicks", async () => {
    const { default: MapboxDraw } = await import("@mapbox/mapbox-gl-draw");
    const { applyMapLibreClassesToDraw } = await import("./drawStyles");
    applyMapLibreClassesToDraw(MapboxDraw);
    const classes = (MapboxDraw as unknown as { constants: { classes: Record<string, string> } })
      .constants.classes;
    expect(classes.CONTROL_BASE).toBe("maplibregl-ctrl");
    expect(classes.CONTROL_GROUP).toBe("maplibregl-ctrl-group");
    expect(classes.CONTROL_PREFIX).toBe("maplibregl-ctrl-");
  });
});
