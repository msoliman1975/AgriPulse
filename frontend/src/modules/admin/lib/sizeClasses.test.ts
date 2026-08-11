import { describe, expect, it } from "vitest";

import type { SizeClass } from "@/api/crops";

import { validateSizeClasses } from "./sizeClasses";

function cls(over: Partial<SizeClass> = {}): SizeClass {
  return { code: "small", name_en: "Small", name_ar: "صغير", order: 1, ...over };
}

describe("validateSizeClasses", () => {
  it("accepts a well-formed list", () => {
    expect(validateSizeClasses([cls(), cls({ code: "large", order: 2 })])).toEqual([]);
  });

  // The backend requires at least one class, and an empty list saved by
  // accident leaves the block's size dropdown with nothing in it.
  it("refuses an empty list", () => {
    expect(validateSizeClasses([])).toHaveLength(1);
  });

  it("catches a duplicate code before the server does", () => {
    const problems = validateSizeClasses([cls(), cls({ order: 2 })]);
    expect(problems.some((p) => p.includes("duplicate code"))).toBe(true);
  });

  it("rejects a code that isn't lower_snake_case", () => {
    const problems = validateSizeClasses([cls({ code: "Small Tree" })]);
    expect(problems.some((p) => p.includes("lower_snake_case"))).toBe(true);
  });

  // Both names are required by the model — an EN-only list renders English
  // inside an otherwise-Arabic form.
  it("requires both names", () => {
    const problems = validateSizeClasses([cls({ name_ar: "  " })]);
    expect(problems.some((p) => p.includes("Arabic name"))).toBe(true);
  });
});
