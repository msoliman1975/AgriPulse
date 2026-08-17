import { describe, expect, it } from "vitest";

import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import {
  classesFor,
  classify,
  histogramBins,
  histogramCeiling,
  histogramFloor,
  INDEX_CLASSES,
  lowerBound,
  titilerColormap,
} from "./indexClasses";

const CODES = Object.keys(INDEX_CLASSES) as ApiIndexCode[];

describe("index class tables", () => {
  it.each(CODES)("%s is ordered ascending and closed at the top", (code) => {
    const classes = classesFor(code);
    expect(classes.length).toBeGreaterThan(0);
    const maxes = classes.map((c) => c.max);
    expect(maxes).toEqual([...maxes].sort((a, b) => a - b));
    expect(maxes[maxes.length - 1]).toBe(Infinity);
    // A duplicated boundary would make one class unreachable.
    expect(new Set(maxes).size).toBe(maxes.length);
  });

  it.each(CODES)("%s paints every class a distinct colour", (code) => {
    const colors = classesFor(code).map((c) => c.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("puts a value exactly on a boundary in the lower class", () => {
    // The rule the tile colormap and the legend both have to agree on.
    expect(classify("ndvi", 0.2)?.key).toBe("verySparse");
    expect(classify("ndvi", 0.200001)?.key).toBe("sparse");
  });

  it("has no reading for null or NaN", () => {
    expect(classify("ndvi", null)).toBeNull();
    expect(classify("ndvi", Number.NaN)).toBeNull();
  });

  it("reads negative NDVI as water, not as bare soil", () => {
    // The class that was missing: water, snow and cloud used to land in
    // "bare soil" and read as dry ground.
    expect(classify("ndvi", -0.15)?.key).toBe("water");
    expect(classify("ndvi", 0.05)?.key).toBe("bare");
  });

  it("reads SAVI on NDVI's cut points, not EVI's", () => {
    // 0.38 is "sparse" on NDVI/SAVI but "developing" on EVI — the one-class
    // flattery that copying EVI's table introduced.
    expect(classify("savi", 0.38)?.key).toBe("sparse");
    expect(classify("ndvi", 0.38)?.key).toBe("sparse");
    expect(classify("evi", 0.38)?.key).toBe("developing");
    expect(classesFor("savi").map((c) => c.max)).toEqual(classesFor("ndvi").map((c) => c.max));
  });

  it("reads NDMI against the published table, not the shipped one", () => {
    // Was "bare" for everything below -0.2; bare soil actually starts at -0.8.
    expect(classify("ndmi", -0.5)?.key).toBe("verySparse");
    expect(classify("ndmi", -0.9)?.key).toBe("bare");
    // The top of the scale is a problem of its own, not the best reading.
    expect(classify("ndmi", 0.9)?.key).toBe("saturated");
    expect(classify("ndmi", 0.7)?.key).toBe("veryDense");
  });

  it("orders NDWI so its healthy end is its negative end", () => {
    // The one index whose scale runs the other way. Colour is a verdict, so
    // the tones — not the numbers — have to descend as the value rises.
    expect(classify("ndwi", -0.6)?.tone).toBe("healthy");
    expect(classify("ndwi", 0.5)?.tone).toBe("critical");
    // McFeeters' own threshold: above zero is water.
    expect(classify("ndwi", 0.01)?.tone).toBe("critical");
    expect(classify("ndwi", -0.01)?.key).toBe("bareOrDamp");
  });

  it("derives a class's lower bound from the class below it", () => {
    expect(lowerBound("ndvi", 0)).toBeNull();
    expect(lowerBound("ndvi", 1)).toBe(0);
    expect(lowerBound("ndvi", 3)).toBe(0.2);
  });
});

describe("histogramBins", () => {
  it.each(CODES)("%s emits N+1 ascending edges", (code) => {
    const bins = histogramBins(code);
    expect(bins).toHaveLength(classesFor(code).length + 1);
    expect(bins).toEqual([...bins].sort((a, b) => a - b));
    expect(bins[0]).toBe(histogramFloor(code));
    expect(bins[bins.length - 1]).toBe(histogramCeiling(code));
  });

  it("keeps EVI's out-of-range pixels inside the end bins", () => {
    // EVI's gain term can push past 1 over bright soil; a clamp at ±1 would
    // drop those pixels out of the histogram and understate the area.
    const bins = histogramBins("evi");
    expect(bins[0]).toBeLessThan(-1);
    expect(bins[bins.length - 1]).toBeGreaterThan(1);
  });

  it.each(CODES)("%s clamps outside its own class boundaries", (code) => {
    // The failure this catches is silent and total. A clamp that does not
    // reach an index's real values leaves its pixels outside every interval,
    // and TiTiler renders those TRANSPARENT — so the map goes blank and the
    // legend reports the ground as unread rather than mis-coloured.
    //
    // `lst` is why this is a per-index question at all: degrees Celsius
    // against a module-wide ceiling of 3, which every real pixel on the
    // reference farm exceeds by an order of magnitude.
    const finite = classesFor(code)
      .map((c) => c.max)
      .filter((m) => Number.isFinite(m));
    expect(histogramFloor(code)).toBeLessThan(Math.min(...finite));
    expect(histogramCeiling(code)).toBeGreaterThan(Math.max(...finite));
  });

  it("reaches the temperatures LST actually reads", () => {
    // Measured on the reference farm: 42.9-56.6 °C over bare sand in August,
    // and the catalog's own bound for the index is 0-60. A clamp that stopped
    // at either end of that would erase the hottest ground on the map, which
    // is the ground a reader opens LST to find.
    expect(histogramFloor("lst")).toBeLessThan(0);
    expect(histogramCeiling("lst")).toBeGreaterThan(60);
  });
});

describe("titilerColormap", () => {
  it.each(CODES)("%s covers the range with contiguous intervals", (code) => {
    const cm = JSON.parse(titilerColormap(code)) as [[number, number], number[]][];
    expect(cm).toHaveLength(classesFor(code).length);
    expect(cm[0][0][0]).toBe(histogramFloor(code));
    expect(cm[cm.length - 1][0][1]).toBe(histogramCeiling(code));
    // No gaps and no overlaps: every value in range gets exactly one colour.
    for (let i = 1; i < cm.length; i += 1) {
      expect(cm[i][0][0]).toBe(cm[i - 1][0][1]);
    }
  });

  it.each(CODES)("%s sends the legend's own colours to the tile server", (code) => {
    // The guarantee the whole redesign rests on: what the map paints and what
    // the legend draws come from one table, so they cannot drift.
    const cm = JSON.parse(titilerColormap(code)) as [[number, number], number[]][];
    const asHex = cm.map(
      ([, [r, g, b]]) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`,
    );
    expect(asHex).toEqual(classesFor(code).map((c) => c.color));
    for (const [, rgba] of cm) expect(rgba[3]).toBe(255);
  });

  it("emits JSON TiTiler can parse as intervals", () => {
    const raw = titilerColormap("ndvi");
    expect(() => JSON.parse(raw)).not.toThrow();
    // [[min, max], [r, g, b, a]] — the shape TiTiler's `colormap` expects.
    const first = JSON.parse(raw)[0];
    expect(first[0]).toHaveLength(2);
    expect(first[1]).toHaveLength(4);
  });
});
