import { describe, expect, it } from "vitest";

import {
  DIMENSIONLESS_DECIMALS,
  formatIndexTick,
  formatIndexValue,
  indexDecimals,
} from "./indexFormat";

describe("indexDecimals", () => {
  it("defaults to the dimensionless precision", () => {
    expect(indexDecimals("")).toBe(DIMENSIONLESS_DECIMALS);
    expect(indexDecimals(null)).toBe(DIMENSIONLESS_DECIMALS);
    expect(indexDecimals(undefined)).toBe(DIMENSIONLESS_DECIMALS);
  });

  it("uses one decimal for degrees Celsius", () => {
    // The thermal band is 100 m native resampled onto a 30 m grid. Three
    // decimals would be false precision dressed up as rigour.
    expect(indexDecimals("°C")).toBe(1);
  });

  it("falls back to the default for a unit it has never seen", () => {
    expect(indexDecimals("kPa")).toBe(DIMENSIONLESS_DECIMALS);
  });
});

describe("formatIndexValue", () => {
  it("renders a dimensionless index as a bare number", () => {
    expect(formatIndexValue(0.7234, "")).toBe("0.723");
  });

  it("appends the unit when there is one", () => {
    expect(formatIndexValue(31.847, "°C")).toBe("31.8 °C");
  });

  it("keeps msi's ratio at dimensionless precision", () => {
    // msi is [0, 3] rather than [-1, 1], but still dimensionless.
    expect(formatIndexValue(1.2345, "")).toBe("1.234");
  });

  it("renders an em dash for a missing value rather than 0", () => {
    // A no-data pixel is not a zero reading, and 0.000 would be a lie.
    expect(formatIndexValue(null, "")).toBe("—");
    expect(formatIndexValue(undefined, "°C")).toBe("—");
    expect(formatIndexValue(Number.NaN, "")).toBe("—");
  });

  it("handles negative values, which normalized differences reach", () => {
    expect(formatIndexValue(-0.4321, "")).toBe("-0.432");
  });
});

describe("formatIndexTick", () => {
  it("omits the unit — that belongs on the axis label, not every tick", () => {
    expect(formatIndexTick(31.847, "°C")).toBe("31.8");
    expect(formatIndexTick(0.7234, "")).toBe("0.723");
  });

  it("renders nothing for a missing value", () => {
    expect(formatIndexTick(null, "°C")).toBe("");
  });
});
