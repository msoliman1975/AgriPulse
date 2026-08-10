import { describe, expect, it } from "vitest";

import type { Crop, CropVariety, CropVarietyStrain, PhenologyStage } from "@/api/crops";

import {
  chainPath,
  deepestLevel,
  ownsValue,
  resolvePhenology,
  resolveSizeClasses,
  resolveThresholds,
  sourcePath,
  thresholdSources,
} from "./cropTaxonomy";

function stage(code: string): PhenologyStage {
  return {
    code,
    name_en: code,
    name_ar: code,
    order: 0,
    advance: { mode: "calendar_doy", start_doy: "01-01", end_doy: "12-31" },
  };
}

const CROP: Crop = {
  id: "c1",
  code: "mango",
  name_en: "Mango",
  name_ar: "مانجو",
  scientific_name: null,
  category: "fruit_tree",
  is_perennial: true,
  default_growing_season_days: null,
  relevant_indices: ["ndvi"],
  classification_depth: "variety_strain",
  is_active: true,
  phenology_stages: { stages: [stage("crop_a"), stage("crop_b")] },
  size_classes: { classes: [{ code: "small", name_en: "Small", name_ar: "صغير", order: 0 }] },
  default_thresholds: { frost_threshold_c: 2, ndvi_warn: -10 },
};

const VARIETY: CropVariety = {
  id: "v1",
  crop_id: "c1",
  code: "alphonso",
  name_en: "Alphonso",
  name_ar: null,
  path: "mango.alphonso",
  is_active: true,
};

const STRAIN: CropVarietyStrain = {
  id: "s1",
  crop_variety_id: "v1",
  code: "a1",
  name_en: "Clone A1",
  name_ar: null,
  path: "mango.alphonso.a1",
  is_active: true,
};

describe("resolvePhenology", () => {
  it("falls back to the crop when nothing overrides", () => {
    const r = resolvePhenology({ crop: CROP, variety: VARIETY, strain: STRAIN });
    expect(r.source).toBe("crop");
    expect(r.value?.map((s) => s.code)).toEqual(["crop_a", "crop_b"]);
  });

  it("lets a variety replace the crop's calendar wholesale", () => {
    const variety = { ...VARIETY, phenology_stages_override: { stages: [stage("v_only")] } };
    const r = resolvePhenology({ crop: CROP, variety });
    expect(r.source).toBe("variety");
    // Wholesale, not merged: the crop's two stages are gone, not appended to.
    expect(r.value?.map((s) => s.code)).toEqual(["v_only"]);
  });

  it("resolves a strain to its variety, not to the crop", () => {
    const variety = { ...VARIETY, phenology_stages_override: { stages: [stage("v_only")] } };
    const r = resolvePhenology({ crop: CROP, variety, strain: STRAIN });
    expect(r.source).toBe("variety");
    expect(r.value?.map((s) => s.code)).toEqual(["v_only"]);
  });

  it("lets a strain beat its variety", () => {
    const variety = { ...VARIETY, phenology_stages_override: { stages: [stage("v_only")] } };
    const strain = { ...STRAIN, phenology_stages_override: { stages: [stage("s_only")] } };
    expect(resolvePhenology({ crop: CROP, variety, strain }).source).toBe("strain");
  });

  it("treats two varieties of one crop independently", () => {
    const alphonso = { ...VARIETY, phenology_stages_override: { stages: [stage("early")] } };
    const kitti: CropVariety = { ...VARIETY, id: "v2", code: "kitti", path: "mango.kitti" };
    expect(resolvePhenology({ crop: CROP, variety: alphonso }).value?.[0].code).toBe("early");
    expect(resolvePhenology({ crop: CROP, variety: kitti }).source).toBe("crop");
  });

  it("reports no source when no level defines a calendar", () => {
    const crop = { ...CROP, phenology_stages: null };
    expect(resolvePhenology({ crop })).toEqual({ value: null, source: null });
  });

  it("distinguishes a cleared override from an absent one", () => {
    // Both mean "inherit" — null is what clearing writes, undefined is what a
    // response omits. Neither may shadow the parent.
    const cleared = { ...VARIETY, phenology_stages_override: null };
    expect(resolvePhenology({ crop: CROP, variety: cleared }).source).toBe("crop");
  });
});

describe("resolveSizeClasses", () => {
  it("mirrors the phenology rule", () => {
    const variety = {
      ...VARIETY,
      size_classes_override: {
        classes: [{ code: "big", name_en: "Big", name_ar: "كبير", order: 0 }],
      },
    };
    const r = resolveSizeClasses({ crop: CROP, variety, strain: STRAIN });
    expect(r.source).toBe("variety");
    expect(r.value?.map((c) => c.code)).toEqual(["big"]);
  });
});

describe("resolveThresholds", () => {
  it("shallow-merges per key rather than replacing", () => {
    const variety = { ...VARIETY, default_thresholds: { ndvi_warn: -15 } };
    const strain = { ...STRAIN, default_thresholds: { frost_threshold_c: 0 } };
    expect(resolveThresholds({ crop: CROP, variety, strain })).toEqual({
      frost_threshold_c: 0,
      ndvi_warn: -15,
    });
  });

  it("collapses to an empty object when nothing is set", () => {
    expect(resolveThresholds({ crop: { ...CROP, default_thresholds: null } })).toEqual({});
  });

  it("reports the winning level per key", () => {
    const variety = { ...VARIETY, default_thresholds: { ndvi_warn: -15 } };
    expect(thresholdSources({ crop: CROP, variety })).toEqual({
      frost_threshold_c: "crop",
      ndvi_warn: "variety",
    });
  });
});

describe("ownership", () => {
  it("only the level that defines a value owns it", () => {
    const variety = { ...VARIETY, phenology_stages_override: { stages: [stage("v")] } };
    // Standing on the variety that defines it: editable in place.
    expect(ownsValue({ crop: CROP, variety }, "variety")).toBe(true);
    // Standing on the strain below it: inherited, so read-only.
    expect(ownsValue({ crop: CROP, variety, strain: STRAIN }, "variety")).toBe(false);
  });

  it("names the level and path an edit would land on", () => {
    const chain = { crop: CROP, variety: VARIETY, strain: STRAIN };
    expect(deepestLevel(chain)).toBe("strain");
    expect(chainPath(chain)).toBe("mango.alphonso.a1");
    expect(sourcePath(chain, "crop")).toBe("mango");
    expect(sourcePath(chain, "variety")).toBe("mango.alphonso");
  });
});
