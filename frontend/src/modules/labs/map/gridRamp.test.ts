import { describe, expect, it } from "vitest";

import type { IndexCode } from "@/api/indices";
import { NO_DATA_COLOR, classesFor } from "../console/indexClasses";
import { GRID_NO_DATA, gridRampExpression } from "./gridRamp";

/**
 * Walk the `["case", cond, grey, ["step", input, c0, s1, c1, ...]]` shape the
 * builder emits and return the colour it would paint for `value`.
 *
 * Evaluating the expression rather than asserting its literal shape means
 * these tests describe what an operator SEES, and survive a rewrite of how
 * the expression is assembled.
 */
function paint(code: IndexCode | null, value: number): string {
  const expr = gridRampExpression(code);
  // No index selected collapses to a flat colour, not an expression.
  if (typeof expr === "string") return expr;
  if (value === GRID_NO_DATA) return expr[2] as string;
  const step = expr[3] as unknown[];
  // ["step", input, defaultOut, stop1, out1, stop2, out2, ...]
  let out = step[2] as string;
  for (let i = 3; i < step.length; i += 2) {
    if (value >= (step[i] as number)) out = step[i + 1] as string;
  }
  return out;
}

describe("gridRampExpression", () => {
  it("paints the no-data sentinel grey for every index", () => {
    for (const code of ["ndvi", "ndwi", "ndmi", "bsi", "msi"] as IndexCode[]) {
      expect(paint(code, GRID_NO_DATA), code).toBe(NO_DATA_COLOR);
    }
  });

  it("paints every cell grey when no index is selected", () => {
    // Guessing NDVI's verdict for an unknown quantity would be worse than
    // admitting there is nothing to say.
    expect(paint(null, 0.8)).toBe(NO_DATA_COLOR);
  });

  it("uses each index's own class colours, not one shared ramp", () => {
    for (const code of ["ndvi", "ndwi", "ndmi", "bsi", "msi"] as IndexCode[]) {
      const classes = classesFor(code);
      // A value comfortably inside the first class paints that class.
      const wellInsideFirst = classes[0].max - 0.05;
      expect(paint(code, wellInsideFirst), code).toBe(classes[0].color);
      // ...and one above the last cut point paints the last class.
      const lastCut = classes[classes.length - 2].max;
      expect(paint(code, lastCut + 0.05), code).toBe(classes[classes.length - 1].color);
    }
  });

  it("reads MSI as a ratio where high is bad — the regression that forced this", () => {
    // Under the old index-agnostic ramp every stop above 0.85 was the healthy
    // green, so a severely stressed block (MSI well above 1.0) rendered as the
    // most reassuring colour on the map. These are the readings that broke.
    const classes = classesFor("msi");
    const healthiest = classes[0].color;
    const worst = classes[classes.length - 1].color;

    expect(paint("msi", 0.25)).toBe(healthiest); // well watered
    expect(paint("msi", 2.0)).toBe(worst); // parched
    expect(paint("msi", 2.0)).not.toBe(paint("msi", 0.25));
  });

  it("reads BSI with its healthy end negative, like NDWI", () => {
    // Bare-soil and surface-water indices both invert against the canopy
    // indices: the good news is at the bottom of the scale.
    const bsi = classesFor("bsi");
    expect(paint("bsi", -0.5)).toBe(bsi[0].color); // closed canopy
    expect(paint("bsi", 0.5)).toBe(bsi[bsi.length - 1].color); // bare ground
    expect(paint("bsi", -0.5)).not.toBe(paint("bsi", 0.5));
  });

  it("keeps NDVI's ordering the other way round", () => {
    // The sanity check on the two above: for a canopy index, high is good.
    const ndvi = classesFor("ndvi");
    expect(paint("ndvi", 0.9)).toBe(ndvi[ndvi.length - 1].color);
    expect(paint("ndvi", 0.9)).not.toBe(paint("ndvi", 0.05));
  });
});
