import { describe, expect, it } from "vitest";

import type { Crop, CropAttributeDefinition, CropVariety, CropVarietyStrain } from "@/api/crops";

import { scopedAttributes } from "./scopedAttributes";

const CROP = { id: "c1", code: "mango" } as Crop;
const VARIETY = { id: "v1", path: "mango.alphonso" } as CropVariety;
const STRAIN = { id: "s1", path: "mango.alphonso.a1" } as CropVarietyStrain;
const OTHER_VARIETY = { id: "v2", path: "mango.kitti" } as CropVariety;

function def(path: string, code: string, sort = 0): CropAttributeDefinition {
  return { id: `${path}:${code}`, path, code, sort_order: sort } as CropAttributeDefinition;
}

describe("scopedAttributes", () => {
  const all = [
    def("mango", "rootstock", 1),
    def("mango", "spacing", 2),
    def("mango.alphonso", "spacing", 2), // overrides the crop's
    def("mango.alphonso", "irrigation", 3),
    def("mango.alphonso.a1", "irrigation", 3), // overrides the variety's
    def("mango.kitti", "pruning", 4), // a sibling — never in scope
  ];

  it("splits a crop's own definitions from nothing inherited", () => {
    const { attached, inherited } = scopedAttributes(all, { crop: CROP });
    expect(attached.map((d) => d.code)).toEqual(["rootstock", "spacing"]);
    expect(inherited).toEqual([]);
  });

  it("lets a deeper definition win per code, unlike the wholesale ladders", () => {
    const { attached, inherited } = scopedAttributes(all, { crop: CROP, variety: VARIETY });
    // spacing is replaced at the variety, so only the variety's copy survives.
    expect(attached.map((d) => d.path + ":" + d.code)).toEqual([
      "mango.alphonso:spacing",
      "mango.alphonso:irrigation",
    ]);
    // rootstock is untouched at the crop and still applies — a per-key
    // resolution, not a wholesale replacement.
    expect(inherited.map((d) => d.code)).toEqual(["rootstock"]);
  });

  it("resolves a strain against its own variety, not straight to the crop", () => {
    const { attached, inherited } = scopedAttributes(all, {
      crop: CROP,
      variety: VARIETY,
      strain: STRAIN,
    });
    expect(attached.map((d) => d.path)).toEqual(["mango.alphonso.a1"]);
    expect(inherited.map((d) => d.path + ":" + d.code)).toEqual([
      "mango:rootstock",
      "mango.alphonso:spacing",
    ]);
  });

  it("ignores a sibling branch entirely", () => {
    const scoped = scopedAttributes(all, { crop: CROP, variety: VARIETY });
    expect([...scoped.attached, ...scoped.inherited].some((d) => d.code === "pruning")).toBe(false);
    // …and picks it up on the branch it actually belongs to.
    const sibling = scopedAttributes(all, { crop: CROP, variety: OTHER_VARIETY });
    expect(sibling.attached.map((d) => d.code)).toEqual(["pruning"]);
  });
});
