import { describe, expect, it } from "vitest";

import {
  parseConditionTree,
  serializeCondition,
  type ComparisonTerm,
} from "./conditionEdit";

describe("parseConditionTree", () => {
  it("parses a single comparison", () => {
    const raw = {
      op: "lt",
      left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
      right: -0.5,
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("single");
    if (result.kind !== "single") return;
    expect(result.term.op).toBe("lt");
    expect(result.term.left).toEqual({
      source: "indices",
      index_code: "ndvi",
      key: "baseline_deviation",
    });
    expect(result.term.right).toEqual({ kind: "number", value: -0.5 });
  });

  it("parses an all_of group with multiple terms", () => {
    const raw = {
      all_of: [
        {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -0.5,
        },
        {
          op: "gt",
          left: { source: "signals", code: "soil_moisture", key: "value_numeric" },
          right: 30,
        },
      ],
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("group");
    if (result.kind !== "group") return;
    expect(result.mode).toBe("all");
    expect(result.terms.length).toBe(2);
    expect(result.terms[1].left).toEqual({
      source: "signals",
      code: "soil_moisture",
      key: "value_numeric",
    });
  });

  it("collapses a single-element all_of into a single comparison", () => {
    const raw = {
      all_of: [
        {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -0.5,
        },
      ],
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("single");
  });

  it("flags nested groups as unsupported", () => {
    const raw = {
      all_of: [
        { all_of: [{ op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 }] },
      ],
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("unsupported");
  });

  it("flags `not` as unsupported", () => {
    const raw = {
      not: { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("flags `between` op as unsupported", () => {
    const raw = {
      op: "between",
      left: { source: "indices", index_code: "ndvi", key: "mean" },
      low: 0,
      high: 1,
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("treats undefined as empty", () => {
    expect(parseConditionTree(undefined).kind).toBe("empty");
  });

  it("parses a grid anomaly ref (G-4)", () => {
    const raw = {
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "flagged_count" },
      right: 5,
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("single");
    if (result.kind !== "single") return;
    expect(result.term.left).toEqual({
      source: "grid",
      index_code: "ndvi",
      field: "flagged_count",
    });
  });

  it("rejects an unknown grid field (falls to unsupported)", () => {
    const raw = {
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "bogus" },
      right: 5,
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("parses a params ref on the right operand", () => {
    const raw = {
      op: "lt",
      left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
      right: { source: "params", name: "ndvi_threshold" },
    };
    const result = parseConditionTree(raw);
    expect(result.kind).toBe("single");
    if (result.kind !== "single") return;
    expect(result.term.right).toEqual({
      kind: "ref",
      ref: { source: "params", name: "ndvi_threshold" },
    });
  });
});

describe("round-trip", () => {
  it("preserves the seed-style single comparison", () => {
    const original = {
      op: "lt",
      left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
      right: -0.5,
    };
    const parsed = parseConditionTree(original);
    const back = serializeCondition(parsed);
    expect(back).toEqual(original);
  });

  it("preserves the unsupported AST untouched", () => {
    const original = {
      not: { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
    };
    const parsed = parseConditionTree(original);
    const back = serializeCondition(parsed);
    expect(back).toEqual(original);
  });

  it("preserves a grid anomaly comparison (G-4)", () => {
    const original = {
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "flagged_count" },
      right: 5,
    };
    const parsed = parseConditionTree(original);
    const back = serializeCondition(parsed);
    expect(back).toEqual(original);
  });

  it("preserves an all_of group", () => {
    const term1: ComparisonTerm = {
      op: "lt",
      left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
      right: { kind: "number", value: -0.5 },
    };
    const term2: ComparisonTerm = {
      op: "gt",
      left: { source: "signals", code: "soil_moisture", key: "value_numeric" },
      right: { kind: "number", value: 30 },
    };
    const back = serializeCondition({ kind: "group", mode: "all", terms: [term1, term2] });
    expect(back).toEqual({
      all_of: [
        {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -0.5,
        },
        {
          op: "gt",
          left: { source: "signals", code: "soil_moisture", key: "value_numeric" },
          right: 30,
        },
      ],
    });
  });
});
