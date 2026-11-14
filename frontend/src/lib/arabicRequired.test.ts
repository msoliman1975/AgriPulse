import { describe, expect, it } from "vitest";

import { needsArabic } from "./arabicRequired";

describe("needsArabic (D26)", () => {
  it("asks for Arabic on new English text", () => {
    expect(needsArabic("Keitt", "")).toBe(true);
    expect(needsArabic("Keitt", "   ")).toBe(true);
    expect(needsArabic("Keitt", null)).toBe(true);
  });

  it("is satisfied by Arabic, or by no English at all", () => {
    expect(needsArabic("Keitt", "كيت")).toBe(false);
    expect(needsArabic("", "")).toBe(false);
    expect(needsArabic(null, undefined)).toBe(false);
  });

  it("leaves an untouched English-only record alone", () => {
    expect(needsArabic("Keitt", "", { en: "Keitt", ar: null })).toBe(false);
    expect(needsArabic(" Keitt ", "", { en: "Keitt", ar: null })).toBe(false);
  });

  it("asks again once the English changes, or the Arabic is cleared", () => {
    expect(needsArabic("Keitt mango", "", { en: "Keitt", ar: null })).toBe(true);
    expect(needsArabic("Keitt", "", { en: "Keitt", ar: "كيت" })).toBe(true);
  });
});
