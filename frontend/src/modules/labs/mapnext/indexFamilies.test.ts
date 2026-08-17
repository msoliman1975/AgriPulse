// The family tabs are generated from INDEX_FAMILIES, so an index missing from
// that table does not error — it just stops being reachable anywhere in the
// dock. These keep the three index tables in lock-step instead.
import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/farmConsole.json";
import en from "@/i18n/locales/en/farmConsole.json";
import {
  BLOCK_LEVEL_INDICES,
  FAMILY_PRIMARY,
  INDEX_BANDS,
  INDEX_FAMILIES,
  INDEX_META,
  isBlockLevel,
  MAP_INDEX_ORDER,
} from "./constants";
import { bandFor } from "./dockFormat";

const LOCALES: [string, Record<string, unknown>][] = [
  ["en", en],
  ["ar", ar],
];

/** `dock.band.ndvi.bare` → the string, or undefined. i18next resolves a
 * missing key to the key itself, so an assertion on the rendered text would
 * pass on a typo; walking the bundle is the only check that actually fails. */
function lookup(bundle: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node == null || typeof node !== "object") return undefined;
    return (node as Record<string, unknown>)[part];
  }, bundle);
}

describe("index families", () => {
  it("files every index the map can colour by into exactly one family", () => {
    const filed = INDEX_FAMILIES.flatMap((f) => f.indices);
    expect([...filed].sort()).toEqual([...MAP_INDEX_ORDER].sort());
    expect(new Set(filed).size).toBe(filed.length);
  });

  it("agrees with the family recorded on each index", () => {
    for (const family of INDEX_FAMILIES) {
      for (const code of family.indices) {
        expect(INDEX_META[code].family).toBe(family.key);
      }
    }
  });

  it("gives each family at most one block-level index, and charts exactly it", () => {
    for (const family of INDEX_FAMILIES) {
      const blockLevel = family.indices.filter(isBlockLevel);
      // More than one and the tab would have to choose which to plot.
      expect(blockLevel.length, family.key).toBeLessThanOrEqual(1);
      // NONE is allowed, and `thermal` is the case: the block-level timeseries
      // route serves the three fixed optical columns `blocks_summary_router`
      // publishes, and no thermal index is among them. The tab then says so
      // rather than charting a neighbour under a thermal heading — which is
      // why the primary is nullable and why this asserts the two agree in
      // BOTH directions rather than just that a primary exists.
      expect(FAMILY_PRIMARY[family.key] ?? null, family.key).toBe(blockLevel[0] ?? null);
    }
    expect(Object.values(FAMILY_PRIMARY).filter(Boolean).sort()).toEqual(
      [...BLOCK_LEVEL_INDICES].sort(),
    );
  });
});

describe("index bands", () => {
  it("bands every index the map can colour by", () => {
    expect(Object.keys(INDEX_BANDS).sort()).toEqual([...MAP_INDEX_ORDER].sort());
  });

  it("orders each band list ascending and closes it at Infinity", () => {
    for (const [code, bands] of Object.entries(INDEX_BANDS)) {
      expect(bands.length, code).toBeGreaterThan(1);
      const bounds = bands.map((b) => b.max);
      expect(bounds, code).toEqual([...bounds].sort((a, b) => a - b));
      // Strictly ascending: two bands sharing a ceiling makes the second
      // unreachable, which reads as a missing interpretation, not an error.
      expect(new Set(bounds).size, code).toBe(bounds.length);
      expect(bounds[bounds.length - 1], code).toBe(Infinity);
      expect(new Set(bands.map((b) => b.key)).size, code).toBe(bands.length);
    }
  });

  it("resolves a reading in every band, and nothing without one", () => {
    for (const [code, bands] of Object.entries(INDEX_BANDS)) {
      // The ceiling itself is inclusive, so each band's own max selects it.
      bands.forEach((band, i) => {
        if (band.max === Infinity) return;
        expect(bandFor(code as keyof typeof INDEX_BANDS, band.max)?.key, `${code}#${i}`).toBe(band.key);
      });
      // Above the last finite ceiling you land in the Infinity band.
      const finite = bands.filter((b) => b.max !== Infinity);
      const top = finite[finite.length - 1];
      expect(bandFor(code as keyof typeof INDEX_BANDS, top.max + 0.01)?.key, code).toBe(
        bands[bands.length - 1].key,
      );
      // The bottom band catches anything the formula can physically produce.
      expect(bandFor(code as keyof typeof INDEX_BANDS, -1)?.key, code).toBe(bands[0].key);
    }
    // No value, no verdict — a grid-only index and a block with no clear scene
    // must fall through to the scale text rather than to a fabricated band.
    expect(bandFor("ndvi", null)).toBeNull();
    expect(bandFor("ndvi", undefined)).toBeNull();
    expect(bandFor("ndvi", Number.NaN)).toBeNull();
  });

  it("reads NDWI on its inverted, surface-water scale", () => {
    // Guards the one index whose scale runs the other way: the backend's ndwi
    // is McFeeters (GREEN-NIR)/(GREEN+NIR), so a dense canopy is very negative
    // and a positive reading is standing water — not a well-watered crop.
    expect(bandFor("ndwi", -0.55)?.tone).toBe("healthy");
    expect(bandFor("ndwi", 0.35)?.tone).toBe("critical");
    // NDMI, by contrast, is the leaf-moisture index: low means water stress.
    expect(bandFor("ndmi", -0.1)?.tone).toBe("critical");
    expect(bandFor("ndmi", 0.5)?.tone).toBe("healthy");
  });
});

describe("index copy", () => {
  // Definitions, scales and band readings are looked up by interpolated key,
  // so a missing one renders the raw key path into the dock instead of failing.
  it.each(LOCALES)("has a definition and a scale for every index in %s", (_name, bundle) => {
    for (const code of MAP_INDEX_ORDER) {
      expect(lookup(bundle, `dock.def.${code}`), code).toEqual(expect.any(String));
      expect(lookup(bundle, `dock.scale.${code}`), code).toEqual(expect.any(String));
    }
  });

  it.each(LOCALES)("has a reading for every band in %s", (_name, bundle) => {
    for (const [code, bands] of Object.entries(INDEX_BANDS)) {
      for (const band of bands) {
        expect(lookup(bundle, `dock.band.${code}.${band.key}`), `${code}.${band.key}`).toEqual(
          expect.any(String),
        );
      }
    }
  });

  it.each(LOCALES)("carries no band copy for a band that no longer exists in %s", (_name, bundle) => {
    const copy = lookup(bundle, "dock.band") as Record<string, Record<string, string>>;
    expect(Object.keys(copy).sort()).toEqual([...MAP_INDEX_ORDER].sort());
    for (const [code, bands] of Object.entries(INDEX_BANDS)) {
      expect(Object.keys(copy[code]).sort(), code).toEqual(bands.map((b) => b.key).sort());
    }
  });

  it.each(LOCALES)("names all three families in %s", (_name, bundle) => {
    for (const family of INDEX_FAMILIES) {
      expect(lookup(bundle, `dock.family.${family.key}`), family.key).toEqual(expect.any(String));
      // The dock tab strip used to carry its own copy of the family names
      // under `dock.tab.*`, so renaming a family renamed the tab and not the
      // heading, or the reverse. There is one name now — keep it that way.
      expect(lookup(bundle, `dock.tab.${family.key}`), family.key).toBeUndefined();
    }
    expect(lookup(bundle, "dock.definition")).toEqual(expect.any(String));
    expect(lookup(bundle, "dock.howToRead")).toEqual(expect.any(String));
    expect(lookup(bundle, "dock.readingCaveat")).toEqual(expect.any(String));
  });
});
