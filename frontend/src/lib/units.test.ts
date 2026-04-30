import { describe, expect, it } from "vitest";
import { formatArea, formatAreaValue, m2ToUnit, unitToM2 } from "./units";

describe("units conversion", () => {
  it("converts m² to feddan", () => {
    expect(m2ToUnit(4200.83, "feddan")).toBeCloseTo(1, 5);
    expect(m2ToUnit(42008.3, "feddan")).toBeCloseTo(10, 5);
  });

  it("converts m² to acre", () => {
    expect(m2ToUnit(4046.86, "acre")).toBeCloseTo(1, 5);
  });

  it("converts m² to hectare", () => {
    expect(m2ToUnit(10000, "hectare")).toBeCloseTo(1, 5);
    expect(m2ToUnit(50000, "hectare")).toBeCloseTo(5, 5);
  });

  it("round-trips through unitToM2", () => {
    for (const unit of ["feddan", "acre", "hectare"] as const) {
      const m2 = unitToM2(2.5, unit);
      expect(m2ToUnit(m2, unit)).toBeCloseTo(2.5, 5);
    }
  });
});

describe("area formatting", () => {
  it("formats with one decimal in en-US", () => {
    expect(formatAreaValue(12.345, { locale: "en" })).toBe("12.3");
  });

  it("uses ar-EG locale for arabic", () => {
    const out = formatAreaValue(1234.5, { locale: "ar" });
    expect(out).toMatch(/1.?234[.,]5/);
  });

  it("formatArea returns unit + value", () => {
    const result = formatArea(8401.66, "feddan", { locale: "en" });
    expect(result.unit).toBe("feddan");
    expect(result.value).toBeCloseTo(2, 3);
    expect(result.formatted).toBe("2.0");
  });
});
