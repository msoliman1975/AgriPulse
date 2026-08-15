import { describe, expect, it } from "vitest";

import {
  THERMAL_NATIVE_RESOLUTION_M,
  isThermalIndex,
  thermalConfidence,
  thermalPixelCount,
} from "./thermalResolution";

describe("isThermalIndex", () => {
  it("recognises the three thermal codes", () => {
    expect(isThermalIndex("lst")).toBe(true);
    expect(isThermalIndex("cwsi")).toBe(true);
    expect(isThermalIndex("smi")).toBe(true);
  });

  it("does not claim the optical indices", () => {
    for (const code of ["ndvi", "ndmi", "msi", "bsi", "ndwi"]) {
      expect(isThermalIndex(code)).toBe(false);
    }
  });
});

describe("thermalConfidence", () => {
  it("calls the smallest real block sub-pixel", () => {
    // 0.53 ha is the smallest block on the reference farm — a fraction of
    // one 100 m thermal pixel, so its value is the surrounding ground's.
    expect(thermalConfidence(0.53)).toBe("subPixel");
  });

  it("calls the average block marginal", () => {
    // 3.10 ha, about 158 m a side — a trend is readable, within-block
    // variation is not.
    expect(thermalConfidence(3.1)).toBe("marginal");
  });

  it("calls the largest real block resolved", () => {
    // 25.07 ha, roughly 5x5 pixels: a real surface.
    expect(thermalConfidence(25.07)).toBe("resolved");
  });

  it("puts the sub-pixel boundary at one whole pixel", () => {
    expect(thermalConfidence(0.99)).toBe("subPixel");
    expect(thermalConfidence(1)).toBe("marginal");
  });

  it("puts the resolved boundary at a 3x3 neighbourhood", () => {
    expect(thermalConfidence(8.99)).toBe("marginal");
    expect(thermalConfidence(9)).toBe("resolved");
  });

  it("returns null for an unusable area rather than guessing", () => {
    expect(thermalConfidence(null)).toBeNull();
    expect(thermalConfidence(undefined)).toBeNull();
    expect(thermalConfidence(0)).toBeNull();
    expect(thermalConfidence(-4)).toBeNull();
    expect(thermalConfidence(Number.NaN)).toBeNull();
  });
});

describe("thermalPixelCount", () => {
  it("counts whole pixels for a label", () => {
    expect(thermalPixelCount(25.07)).toBe(25);
    expect(thermalPixelCount(3.1)).toBe(3);
  });

  it("is null when there is no usable area", () => {
    expect(thermalPixelCount(0)).toBeNull();
  });
});

describe("THERMAL_NATIVE_RESOLUTION_M", () => {
  it("is the native sensor resolution, not the 30 m delivery grid", () => {
    // The 30 m is a resampling artefact. Labelling the data 30 m would
    // overstate it by more than a factor of three in each direction.
    expect(THERMAL_NATIVE_RESOLUTION_M).toBe(100);
  });
});
