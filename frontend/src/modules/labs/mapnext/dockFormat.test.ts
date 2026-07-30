import { describe, expect, it } from "vitest";

import type { ExplainStep } from "@/api/recommendations";
import {
  decisionSteps,
  failingCount,
  isoDaysBefore,
  leafStep,
  readCondition,
  refKey,
} from "./dockFormat";

function step(partial: Partial<ExplainStep>): ExplainStep {
  return {
    node_id: "n",
    matched: false,
    label_en: "check",
    label_ar: null,
    values: {},
    condition: null,
    ...partial,
  };
}

describe("refKey", () => {
  it("builds the dotted key the backend files values under", () => {
    expect(refKey({ source: "indices", index_code: "ndvi", key: "mean" })).toBe("indices.ndvi.mean");
    expect(refKey({ source: "params", name: "threshold" })).toBe("params.threshold");
    expect(refKey({ source: "block", field: "crop_category" })).toBe("block.crop_category");
    expect(refKey({ source: "weather", scope: "forecast_24h", field: "temp_c_max" })).toBe(
      "weather.forecast_24h.temp_c_max",
    );
  });

  it("returns null for things that aren't refs", () => {
    expect(refKey(0.45)).toBeNull();
    expect(refKey(null)).toBeNull();
    expect(refKey({ nope: true })).toBeNull();
  });
});

describe("readCondition", () => {
  it("pairs the measured value with the threshold it missed", () => {
    const r = readCondition(
      step({
        matched: false,
        values: { "indices.ndvi.mean": "0.39" },
        condition: {
          op: "ge",
          left: { source: "indices", index_code: "ndvi", key: "mean" },
          right: 0.45,
        },
      }),
    );
    expect(r.actual).toBe("0.39");
    expect(r.threshold).toBe("≥ 0.45");
  });

  it("resolves a threshold that is itself a ref, so params read as numbers", () => {
    const r = readCondition(
      step({
        values: { "indices.ndvi.baseline_deviation": "-1.8", "params.warning_threshold": "-1.5" },
        condition: {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: { source: "params", name: "warning_threshold" },
        },
      }),
    );
    expect(r.actual).toBe("-1.8");
    // Not "params.warning_threshold" — the reader needs the number.
    expect(r.threshold).toBe("< -1.5");
  });

  it("renders a between range", () => {
    const r = readCondition(
      step({
        values: { "signals.soil_moisture.value": "22" },
        condition: {
          op: "between",
          left: { source: "signals", code: "soil_moisture", key: "value" },
          low: 35,
          high: 50,
        },
      }),
    );
    expect(r.actual).toBe("22");
    expect(r.threshold).toBe("35–50");
  });

  it("renders an in-list", () => {
    const r = readCondition(
      step({
        values: { "block.growth_stage": "fruit_set" },
        condition: {
          op: "in",
          left: { source: "block", field: "growth_stage" },
          values: ["flowering", "fruit_set"],
        },
      }),
    );
    expect(r.threshold).toBe("flowering, fruit_set");
  });

  it("falls back to listing resolved values for compound conditions", () => {
    const r = readCondition(
      step({
        values: { "indices.ndvi.mean": "0.39", "indices.ndwi.mean": "-0.08" },
        condition: { all_of: [{ op: "ge" }, { op: "lt" }] },
      }),
    );
    // No single threshold to show, but the numbers are still worth surfacing.
    expect(r.actual).toBeNull();
    expect(r.threshold).toBeNull();
    expect(r.values).toHaveLength(2);
  });

  it("does not stringify a ref object into [object Object]", () => {
    const r = readCondition(
      step({
        values: {}, // the right-hand ref never resolved
        condition: {
          op: "ge",
          left: { source: "indices", index_code: "ndvi", key: "mean" },
          right: { source: "params", name: "missing" },
        },
      }),
    );
    expect(r.threshold).toBeNull();
  });

  it("returns nothing to compare for a leaf step", () => {
    const r = readCondition(step({ matched: null, condition: null }));
    expect(r.actual).toBeNull();
    expect(r.threshold).toBeNull();
  });
});

describe("step partitioning", () => {
  const steps = [
    step({ node_id: "a", matched: true }),
    step({ node_id: "b", matched: false }),
    step({ node_id: "leaf", matched: null }),
  ];

  it("separates checks from the verdict leaf", () => {
    expect(decisionSteps(steps).map((s) => s.node_id)).toEqual(["a", "b"]);
    expect(leafStep(steps)?.node_id).toBe("leaf");
  });

  it("counts only failed checks", () => {
    expect(failingCount(steps)).toBe(1);
  });

  it("has no leaf when the walk errored before reaching one", () => {
    expect(leafStep([step({ matched: true })])).toBeNull();
  });
});

describe("isoDaysBefore", () => {
  it("counts back from the given day", () => {
    expect(isoDaysBefore(30, new Date("2026-06-30T00:00:00Z"))).toBe("2026-05-31");
  });
});
