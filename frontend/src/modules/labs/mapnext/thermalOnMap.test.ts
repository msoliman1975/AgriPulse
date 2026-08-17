// Thermal on the map: the invariants that make LST/CWSI/SMI drawable rather
// than merely listed.
//
// Adding three strings to a picker is the easy half and the half that looks
// finished. These cover the parts that go wrong silently — an index offered by
// a console that cannot draw it, a clamp that erases the pixels it was meant
// to colour, and two tables naming the same reading differently.
import { describe, expect, it } from "vitest";

import { THERMAL_INDEX_CODES } from "@/api/indices";
import {
  classesFor,
  histogramCeiling,
  histogramFloor,
  INDEX_CLASSES,
} from "../console/indexClasses";
import {
  INDEX_BANDS,
  INDEX_META,
  isThermalIndex,
  MAP_INDEX_ORDER,
  OPTICAL_INDEX_ORDER,
  THERMAL_INDEX_ORDER,
} from "./constants";

describe("thermal index registration", () => {
  it("offers exactly the API's thermal codes, and offers them last", () => {
    // Derived from the API module rather than restated, so a fourth thermal
    // index added there cannot leave the map silently drawing three.
    expect(THERMAL_INDEX_ORDER).toEqual([...THERMAL_INDEX_CODES]);
    expect(MAP_INDEX_ORDER).toEqual([...OPTICAL_INDEX_ORDER, ...THERMAL_INDEX_ORDER]);
    // Contiguous and at the end — the picker draws one heading at the
    // boundary, so an interleaved list would file optical indices under it.
    const first = MAP_INDEX_ORDER.findIndex(isThermalIndex);
    expect(MAP_INDEX_ORDER.slice(first).every(isThermalIndex)).toBe(true);
  });

  it("keeps thermal out of the optical list the live console renders", () => {
    // /labs/map draws an index as sub-block grid cells and nothing else, and
    // no thermal cell row exists — `grid_configs` are per-product and only the
    // optical product has one. A thermal chip there paints an empty farm.
    expect(OPTICAL_INDEX_ORDER.some(isThermalIndex)).toBe(false);
  });

  it("files all three under one family of their own", () => {
    for (const code of THERMAL_INDEX_ORDER) {
      expect(INDEX_META[code].family, code).toBe("thermal");
    }
  });
});

describe("thermal class tables", () => {
  it.each([...THERMAL_INDEX_CODES])("%s is classed, banded and clamped", (code) => {
    expect(INDEX_CLASSES[code]).toBeDefined();
    expect(INDEX_BANDS[code]).toBeDefined();
  });

  it.each([...THERMAL_INDEX_CODES])(
    "%s reads the same in the legend and in the dock",
    (code) => {
      // The pixel console shows both against the SAME number taken from the
      // SAME raster, so naming it `hot` in one and `warm` in the other is a
      // contradiction visible on one screen.
      const legend = classesFor(code).map((c) => ({ max: c.max, key: c.key, tone: c.tone }));
      const dock = INDEX_BANDS[code].map((b) => ({ max: b.max, key: b.key, tone: b.tone }));
      expect(dock).toEqual(legend);
    },
  );

  it("orders LST so that hot is the bad end", () => {
    // Colour is a verdict, not a quantity — so the tones descend as degrees
    // climb, the same construction MSI uses.
    const lst = classesFor("lst");
    expect(lst[0].tone).toBe("healthy");
    expect(lst[lst.length - 1].tone).toBe("critical");
  });

  it("orders SMI so that dry is the bad end, and wet is its own problem", () => {
    const smi = classesFor("smi");
    expect(smi[0].tone).toBe("critical");
    // The wet edge leaves the verdict ramp rather than topping it: that is
    // where over-irrigation lives, not the best possible reading.
    expect(smi[smi.length - 1].tone).toBe("watch");
  });

  it("clamps LST in degrees, not on the normalized-difference scale", () => {
    // The failure this guards is silent and total. Every optical index is
    // bounded near [-1, 1] and the module clamped to ±3 for all of them; LST
    // reads 43-57 °C on the reference farm, so those pixels fell outside every
    // colormap interval — which TiTiler renders TRANSPARENT. Not a wrong
    // colour: a blank map, with the legend reporting the ground as unread.
    expect(histogramCeiling("lst")).toBeGreaterThan(60);
    expect(histogramFloor("lst")).toBeLessThan(0);
    // The 0-1 pair genuinely fits the default clamp and should not have
    // acquired a bespoke one by copy-paste.
    expect(histogramCeiling("cwsi")).toBe(histogramCeiling("ndvi"));
    expect(histogramCeiling("smi")).toBe(histogramCeiling("ndvi"));
  });
});
