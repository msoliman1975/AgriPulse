// Copy parity for the Farm Console v2 surfaces.
//
// Modelled on mapnext/indexFamilies.test.ts, and for the same reason: i18next
// resolves a missing key to the key itself, so a rendered-text assertion
// passes on a typo. These read the bundles directly.
//
// Both directions matter. Missing copy is the obvious failure; ORPHANED copy
// is the one that rots quietly — a band renamed in constants.ts leaves a
// string nobody renders and nobody deletes.
import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/farmConsole.json";
import en from "@/i18n/locales/en/farmConsole.json";
import { INDEX_BANDS, MAP_INDEX_ORDER } from "../mapnext/constants";
import { BAND_VOCAB, LEGEND_HINT } from "./legendBins";
import { RAIL_SORTS } from "./railSort";

const LOCALES: [string, Record<string, unknown>][] = [
  ["en", en],
  ["ar", ar],
];

function lookup(bundle: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object" && part in (node as Record<string, unknown>)) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, bundle);
}

describe.each(LOCALES)("farmConsole legend copy (%s)", (_lang, bundle) => {
  it("has a label for every band of every index", () => {
    const missing: string[] = [];
    for (const code of MAP_INDEX_ORDER) {
      const vocab = BAND_VOCAB[code];
      expect(vocab, `no BAND_VOCAB entry for ${code}`).toBeTruthy();
      for (const band of INDEX_BANDS[code]) {
        const path = `legend.band.${vocab}.${band.key}`;
        if (typeof lookup(bundle, path) !== "string") missing.push(`${code} -> ${path}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("has no orphaned band labels", () => {
    // Every key that exists must be reachable from some index's bands.
    const used = new Set<string>();
    for (const code of MAP_INDEX_ORDER) {
      for (const band of INDEX_BANDS[code]) used.add(`${BAND_VOCAB[code]}.${band.key}`);
    }
    const bands = lookup(bundle, "legend.band") as Record<string, Record<string, string>>;
    const orphans: string[] = [];
    for (const [vocab, entries] of Object.entries(bands ?? {})) {
      for (const key of Object.keys(entries)) {
        if (!used.has(`${vocab}.${key}`)) orphans.push(`legend.band.${vocab}.${key}`);
      }
    }
    expect(orphans).toEqual([]);
  });

  it("has the legend chrome strings", () => {
    const required = [
      "legend.title",
      "legend.scopeFarm",
      "legend.scopeBlock",
      "legend.areaHeader",
      "legend.covered",
      "legend.noData",
      "legend.noDataHint",
      "legend.hint",
      "legend.collapse",
      "legend.expand",
      "legend.emptyNoGridTitle",
      "legend.emptyNoGridBody",
      "legend.emptyNoGridCta",
      "legend.emptyNoSubsTitle",
      "legend.emptyNoSubsBody",
      "legend.emptyNoSubsCta",
      "legend.emptyOffTitle",
      "legend.emptyOffBody",
    ];
    const missing = required.filter((p) => typeof lookup(bundle, p) !== "string");
    expect(missing).toEqual([]);
  });

  it("has a label for every rail sort mode", () => {
    const missing = RAIL_SORTS.filter(
      (s) => typeof lookup(bundle, `railTools.sort.${s}`) !== "string",
    );
    expect(missing).toEqual([]);
  });

  it("has the map dock strings", () => {
    const required = [
      "mapDock.grid",
      "mapDock.gridUnavailable",
      "mapDock.anomaly",
      "mapDock.contrast",
      "mapDock.compare",
      "mapDock.comingSoon",
      "mapDock.fullscreen",
      "mapDock.exitFullscreen",
    ];
    const missing = required.filter((p) => typeof lookup(bundle, p) !== "string");
    expect(missing).toEqual([]);
  });
});

describe("legend hints", () => {
  it("only points at a band that actually exists on that index", () => {
    for (const [code, hint] of Object.entries(LEGEND_HINT)) {
      if (!hint) continue;
      const bands = INDEX_BANDS[code as keyof typeof INDEX_BANDS];
      expect(
        bands.some((b) => b.key === hint.bandKey),
        `LEGEND_HINT.${code} points at band "${hint.bandKey}", which ${code} does not have`,
      ).toBe(true);
    }
  });
});
