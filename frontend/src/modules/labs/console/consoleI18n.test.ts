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
import { MAP_INDEX_ORDER } from "../mapnext/constants";
import { CLASS_HINT, CLASS_VOCAB, classesFor, INDEX_CLASSES } from "./indexClasses";
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
  it("has a label for every class of every index", () => {
    const missing: string[] = [];
    for (const code of MAP_INDEX_ORDER) {
      const vocab = CLASS_VOCAB[code];
      expect(vocab, `no CLASS_VOCAB entry for ${code}`).toBeTruthy();
      for (const cls of classesFor(code)) {
        const path = `legend.class.${vocab}.${cls.key}`;
        if (typeof lookup(bundle, path) !== "string") missing.push(`${code} -> ${path}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("has no orphaned class labels", () => {
    // Every key that exists must be reachable from some index's classes.
    const used = new Set<string>();
    for (const code of MAP_INDEX_ORDER) {
      for (const cls of classesFor(code)) used.add(`${CLASS_VOCAB[code]}.${cls.key}`);
    }
    const classes = lookup(bundle, "legend.class") as Record<string, Record<string, string>>;
    const orphans: string[] = [];
    for (const [vocab, entries] of Object.entries(classes ?? {})) {
      for (const key of Object.keys(entries)) {
        if (!used.has(`${vocab}.${key}`)) orphans.push(`legend.class.${vocab}.${key}`);
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
      "legend.emptyNoSubsTitle",
      "legend.emptyNoSubsBody",
      "legend.emptyNoSubsCta",
      "legend.emptyNoSceneTitle",
      "legend.emptyNoSceneBody",
      "legend.pixelsOffNote",
      "legend.relativeCaveat",
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

  it("has the datapoint control strings", () => {
    const required = [
      "dataControl.index",
      "dataControl.indexTitle",
      "dataControl.indexNone",
      "dataControl.indexNoneHint",
      "dataControl.indexUnavailable",
      "dataControl.alerts",
      "dataControl.flags",
      "dataControl.flagsTitle",
      "dataControl.signals",
      "dataControl.signalsTitle",
      "dataControl.signalsAll",
      "dataControl.signalsNone",
      "dataControl.markLegend",
      "dataControl.on",
      "dataControl.off",
      "dataControl.shown",
      "dataControl.hidden",
      "dataControl.fullscreen",
      "dataControl.exitFullscreen",
    ];
    const missing = required.filter((p) => typeof lookup(bundle, p) !== "string");
    expect(missing).toEqual([]);
  });

  // The tri-state is rendered from a literal array of three modes, and each
  // mode needs both a name and the line under it. A missing one renders the
  // key, which reads as a typo the eye slides over.
  it("has a name and a hint for every flags mode", () => {
    const missing: string[] = [];
    for (const mode of ["current", "historical", "none"]) {
      for (const path of [`dataControl.flagsMode.${mode}`, `dataControl.flagsHint.${mode}`]) {
        if (typeof lookup(bundle, path) !== "string") missing.push(path);
      }
    }
    expect(missing).toEqual([]);
  });

  it("has the top-bar layer strings", () => {
    const required = [
      "layerBar.farmBorders",
      "layerBar.blockBorders",
      "layerBar.cells",
      "layerBar.cellsUnavailable",
      "layerBar.cellsUnavailableShort",
      "layerBar.borderOpacity",
      "layerBar.fillOpacity",
      "layerBar.showLabels",
      "layerBar.labelName",
      "layerBar.labelCrop",
    ];
    const missing = required.filter((p) => typeof lookup(bundle, p) !== "string");
    expect(missing).toEqual([]);
  });

  // Both controls were deleted; their copy must go with them. A namespace
  // nothing renders is the copy that rots — see the header of this file.
  it("has no copy left over from the deleted map dock and layer cards", () => {
    expect(lookup(bundle, "mapDock")).toBeUndefined();
    expect(lookup(bundle, "layerCards")).toBeUndefined();
  });
});

describe("legend hints", () => {
  it("only points at a class that actually exists on that index", () => {
    for (const [code, hint] of Object.entries(CLASS_HINT)) {
      if (!hint) continue;
      const classes = INDEX_CLASSES[code as keyof typeof INDEX_CLASSES];
      expect(
        classes.some((c) => c.key === hint.classKey),
        `CLASS_HINT.${code} points at class "${hint.classKey}", which ${code} does not have`,
      ).toBe(true);
    }
  });
});
