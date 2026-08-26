import { describe, expect, it } from "vitest";

import { localizedField, localizedName } from "./localizedField";

describe("localizedField", () => {
  it("returns the English value when the language is not Arabic", () => {
    expect(localizedField("en", "Field A", "حقل أ")).toBe("Field A");
  });

  it("returns the Arabic value when the language is Arabic", () => {
    expect(localizedField("ar", "Field A", "حقل أ")).toBe("حقل أ");
  });

  it("falls back to English when the Arabic value was never written", () => {
    expect(localizedField("ar", "Field A", null)).toBe("Field A");
    expect(localizedField("ar", "Field A", undefined)).toBe("Field A");
  });

  it("treats a blank Arabic value as not written", () => {
    // A cleared form input posts "", and the DB read path uses
    // NULLIF(name_ar, '') for the same reason: an empty string would render
    // a blank name rather than fall back.
    expect(localizedField("ar", "Field A", "")).toBe("Field A");
    expect(localizedField("ar", "Field A", "   ")).toBe("Field A");
  });

  it("returns null when neither side has a value", () => {
    expect(localizedField("ar", null, null)).toBeNull();
    expect(localizedField("en", null, "حقل")).toBeNull();
  });

  it("falls back to English when the language is undefined", () => {
    expect(localizedField(undefined, "Field A", "حقل أ")).toBe("Field A");
  });
});

describe("localizedName", () => {
  it("returns a string, never null, when English is present", () => {
    expect(localizedName("ar", "Block 1", null)).toBe("Block 1");
    expect(localizedName("ar", "Block 1", "القطعة ١")).toBe("القطعة ١");
    expect(localizedName("en", "Block 1", "القطعة ١")).toBe("Block 1");
  });
});
