import { describe, expect, it } from "vitest";

import type { Crop, CropVariety, CropVarietyStrain } from "@/api/crops";

import { resolveHeatUnits } from "./cropTaxonomy";
import { heatUnitDraft, heatUnitPatch, heatUnitStartError } from "./heatUnits";

const CROP = {
  id: "c",
  code: "date_palm",
  gdd_method: "max",
  gdd_start_kind: "date",
  gdd_start_value: "01-01",
} as Crop;
const VARIETY = {
  id: "v",
  path: "date_palm.medjool",
  gdd_method: "mean",
  gdd_start_kind: "stage",
  gdd_start_value: "pollination",
} as CropVariety;
const STRAIN = { id: "s", path: "date_palm.medjool.x" } as CropVarietyStrain;

describe("resolveHeatUnits (mirrors farms/heat_units.resolve_config)", () => {
  it("takes the deepest non-null method and start", () => {
    const r = resolveHeatUnits({ crop: CROP, variety: VARIETY, strain: STRAIN });
    expect(r.method).toEqual({ value: "mean", source: "variety" });
    expect(r.start).toEqual({ value: { kind: "stage", value: "pollination" }, source: "variety" });
  });

  it("resolves method and start separately", () => {
    const variety = { ...VARIETY, gdd_method: null } as CropVariety;
    const r = resolveHeatUnits({ crop: CROP, variety });
    expect(r.method.source).toBe("crop");
    expect(r.start.source).toBe("variety");
  });

  it("reports nothing when no level sets it", () => {
    const crop = { id: "c", code: "x" } as Crop;
    expect(resolveHeatUnits({ crop })).toEqual({
      method: { value: null, source: null },
      start: { value: null, source: null },
    });
  });
});

describe("heat-unit draft", () => {
  it("round-trips a node's settings", () => {
    expect(heatUnitPatch(heatUnitDraft(VARIETY))).toEqual({
      gdd_method: "mean",
      gdd_start_kind: "stage",
      gdd_start_value: "pollination",
    });
  });

  it("clears to inherit, and drops a value planting does not take", () => {
    expect(heatUnitPatch({ method: "", startKind: "", startValue: "x" })).toEqual({
      gdd_method: null,
      gdd_start_kind: null,
      gdd_start_value: null,
    });
    expect(heatUnitPatch({ method: "max", startKind: "planting", startValue: "03-01" })).toEqual({
      gdd_method: "max",
      gdd_start_kind: "planting",
      gdd_start_value: null,
    });
  });

  it("checks the start like the database does", () => {
    expect(heatUnitStartError({ method: "", startKind: "date", startValue: "3-1" })).toBe(
      "heatUnits.errorDate",
    );
    expect(heatUnitStartError({ method: "", startKind: "date", startValue: "03-01" })).toBeNull();
    expect(heatUnitStartError({ method: "", startKind: "stage", startValue: "" })).toBe(
      "heatUnits.errorStage",
    );
    expect(heatUnitStartError({ method: "", startKind: "planting", startValue: "" })).toBeNull();
  });
});
