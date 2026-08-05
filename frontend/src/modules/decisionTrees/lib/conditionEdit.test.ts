import { describe, expect, it } from "vitest";

import {
  BLOCK_FIELDS,
  INDICES_KEYS,
  SIGNAL_KEYS,
  changeTermOp,
  parseConditionTree,
  serializeCondition,
  serializeNode,
  type ConditionNode,
  type EditableCondition,
  type Term,
} from "./conditionEdit";

/** Unwrap to the parsed node, failing loudly rather than silently
 *  returning early the way the old `if (kind !== …) return` guards did —
 *  those turned a parser regression into a passing test. */
function node(result: EditableCondition): ConditionNode {
  if (result.kind !== "node") {
    throw new Error(`expected a parsed node, got ${result.kind}`);
  }
  return result.node;
}

function term(result: EditableCondition): Term {
  const n = node(result);
  if (n.kind !== "term") throw new Error(`expected a term, got ${n.kind}`);
  return n.term;
}

describe("parseConditionTree", () => {
  it("parses a single comparison", () => {
    const t = term(
      parseConditionTree({
        op: "lt",
        left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
        right: -0.5,
      }),
    );
    expect(t.op).toBe("lt");
    expect(t.left).toEqual({
      source: "indices",
      index_code: "ndvi",
      key: "baseline_deviation",
    });
    if (t.op === "between" || t.op === "in") throw new Error("expected a binary term");
    expect(t.right).toEqual({ kind: "number", value: -0.5 });
  });

  it("parses an all_of group with multiple terms", () => {
    const n = node(
      parseConditionTree({
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
      }),
    );
    if (n.kind !== "group") throw new Error("expected a group");
    expect(n.mode).toBe("all");
    expect(n.children.length).toBe(2);
  });

  it("treats undefined as empty", () => {
    expect(parseConditionTree(undefined).kind).toBe("empty");
  });

  it("treats an empty group as empty", () => {
    expect(parseConditionTree({ all_of: [] }).kind).toBe("empty");
  });

  it("still rejects a genuinely malformed AST", () => {
    // Unknown op — not a shape we declined to model, an invalid one.
    expect(parseConditionTree({ op: "approximately", left: {}, right: 1 }).kind).toBe(
      "unsupported",
    );
    expect(parseConditionTree({ all_of: "not-a-list" }).kind).toBe("unsupported");
  });
});

// The four shapes that used to bail out to the raw-YAML editor. The
// engine has always supported them; only the builder did not.
describe("shapes that were previously unsupported", () => {
  it("parses a nested group", () => {
    const n = node(
      parseConditionTree({
        all_of: [
          { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
          {
            any_of: [
              { op: "gt", left: { source: "indices", index_code: "ndmi", key: "mean" }, right: 1 },
              { op: "gt", left: { source: "indices", index_code: "evi", key: "mean" }, right: 2 },
            ],
          },
        ],
      }),
    );
    if (n.kind !== "group") throw new Error("expected a group");
    expect(n.children.length).toBe(2);
    const nested = n.children[1];
    if (nested.kind !== "group") throw new Error("expected a nested group");
    expect(nested.mode).toBe("any");
    expect(nested.children.length).toBe(2);
  });

  it("parses `not`", () => {
    const n = node(
      parseConditionTree({
        not: { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
      }),
    );
    if (n.kind !== "not") throw new Error("expected a not");
    expect(n.child.kind).toBe("term");
  });

  it("parses `between` with its low/high pair", () => {
    const t = term(
      parseConditionTree({
        op: "between",
        left: { source: "indices", index_code: "ndvi", key: "mean" },
        low: 0.2,
        high: 0.8,
      }),
    );
    if (t.op !== "between") throw new Error("expected between");
    expect(t.low).toEqual({ kind: "number", value: 0.2 });
    expect(t.high).toEqual({ kind: "number", value: 0.8 });
  });

  it("parses `in` with its value list", () => {
    const t = term(
      parseConditionTree({
        op: "in",
        left: { source: "block", field: "growth_stage" },
        values: ["tuber_bulking", "maturation"],
      }),
    );
    if (t.op !== "in") throw new Error("expected in");
    expect(t.values).toEqual([
      { kind: "string", value: "tuber_bulking" },
      { kind: "string", value: "maturation" },
    ]);
  });

  it("rejects `in` without a values list", () => {
    const raw = { op: "in", left: { source: "block", field: "growth_stage" }, values: "nope" };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });
});

// These drifted out of lock-step with the backend once already, which
// silently pushed every stage-gated and trend-based tree into the
// read-only YAML fallback. Pin them.
describe("constants stay in lock-step with the backend", () => {
  it("accepts the KB P2 index trend keys", () => {
    for (const key of ["slope", "delta", "trend_direction"]) {
      expect(INDICES_KEYS).toContain(key);
      const t = term(
        parseConditionTree({
          op: "eq",
          left: { source: "indices", index_code: "ndmi", key },
          right: "falling",
        }),
      );
      expect(t.left).toEqual({ source: "indices", index_code: "ndmi", key });
    }
  });

  it("accepts the KB P3 growth_stage block field", () => {
    expect(BLOCK_FIELDS).toContain("growth_stage");
    const t = term(
      parseConditionTree({
        op: "eq",
        left: { source: "block", field: "growth_stage" },
        right: "tuber_bulking",
      }),
    );
    expect(t.left).toEqual({ source: "block", field: "growth_stage" });
  });

  it("accepts the crop-taxonomy block fields", () => {
    for (const field of ["crop_path", "crop_strain", "soil_texture", "salinity_class"]) {
      expect(BLOCK_FIELDS).toContain(field);
      expect(
        parseConditionTree({ op: "eq", left: { source: "block", field }, right: "x" }).kind,
      ).toBe("node");
    }
  });

  it("accepts the KB P2 signal trend keys", () => {
    for (const key of ["value_slope", "value_delta", "value_trend_direction"]) {
      expect(SIGNAL_KEYS).toContain(key);
      expect(
        parseConditionTree({
          op: "eq",
          left: { source: "signals", code: "soil_moisture", key },
          right: "falling",
        }).kind,
      ).toBe("node");
    }
  });

  it("still rejects a field the backend does not resolve", () => {
    const raw = { op: "eq", left: { source: "block", field: "invented_field" }, right: 1 };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });
});

describe("existing ref sources still parse", () => {
  it("parses a grid anomaly ref (G-4)", () => {
    const t = term(
      parseConditionTree({
        op: "ge",
        left: { source: "grid", index_code: "ndvi", field: "flagged_count" },
        right: 5,
      }),
    );
    expect(t.left).toEqual({ source: "grid", index_code: "ndvi", field: "flagged_count" });
  });

  it("rejects an unknown grid field", () => {
    const raw = {
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "bogus" },
      right: 5,
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("parses a weather_index anomaly ref (PR-W7)", () => {
    const t = term(
      parseConditionTree({
        op: "gt",
        left: { source: "weather_index", index_code: "temperature", key: "baseline_deviation" },
        right: 2,
      }),
    );
    expect(t.left).toEqual({
      source: "weather_index",
      index_code: "temperature",
      key: "baseline_deviation",
    });
  });

  it("rejects an unknown weather index code", () => {
    const raw = {
      op: "gt",
      left: { source: "weather_index", index_code: "not_an_index", key: "value" },
      right: 2,
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("parses the humidity weather index (migration 0049)", () => {
    const t = term(
      parseConditionTree({
        op: "gt",
        left: { source: "weather_index", index_code: "humidity", key: "value" },
        right: 80,
      }),
    );
    expect(t.left).toEqual({ source: "weather_index", index_code: "humidity", key: "value" });
  });

  it("parses a weather_risk score ref (PR-R3)", () => {
    const t = term(
      parseConditionTree({
        op: "ge",
        left: { source: "weather_risk", risk_code: "powdery_mildew", field: "score" },
        right: 70,
      }),
    );
    expect(t.left).toEqual({
      source: "weather_risk",
      risk_code: "powdery_mildew",
      field: "score",
    });
  });

  it("defaults a weather_risk ref field to score", () => {
    const t = term(
      parseConditionTree({
        op: "ge",
        left: { source: "weather_risk", risk_code: "anthracnose" },
        right: 40,
      }),
    );
    expect(t.left).toEqual({ source: "weather_risk", risk_code: "anthracnose", field: "score" });
  });

  it("rejects an unknown weather_risk code", () => {
    const raw = {
      op: "ge",
      left: { source: "weather_risk", risk_code: "locusts", field: "score" },
      right: 50,
    };
    expect(parseConditionTree(raw).kind).toBe("unsupported");
  });

  it("parses a params ref on the right operand", () => {
    const t = term(
      parseConditionTree({
        op: "lt",
        left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
        right: { source: "params", name: "ndvi_threshold" },
      }),
    );
    if (t.op === "between" || t.op === "in") throw new Error("expected a binary term");
    expect(t.right).toEqual({ kind: "ref", ref: { source: "params", name: "ndvi_threshold" } });
  });
});

describe("round-trip", () => {
  const roundTrips = (original: unknown): void => {
    expect(serializeCondition(parseConditionTree(original))).toEqual(original);
  };

  it("preserves the seed-style single comparison", () => {
    roundTrips({
      op: "lt",
      left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
      right: -0.5,
    });
  });

  it("preserves a nested group verbatim", () => {
    roundTrips({
      all_of: [
        { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
        {
          any_of: [
            { op: "gt", left: { source: "indices", index_code: "ndmi", key: "slope" }, right: 1 },
            {
              not: {
                op: "eq",
                left: { source: "block", field: "growth_stage" },
                right: "maturation",
              },
            },
          ],
        },
      ],
    });
  });

  it("preserves `not`", () => {
    roundTrips({
      not: { op: "lt", left: { source: "indices", index_code: "ndvi", key: "mean" }, right: 0 },
    });
  });

  it("preserves `between`", () => {
    roundTrips({
      op: "between",
      left: { source: "weather", scope: "forecast_24h", field: "air_temp_c_max" },
      low: 25,
      high: 35,
    });
  });

  it("preserves `in`", () => {
    roundTrips({
      op: "in",
      left: { source: "block", field: "growth_stage" },
      values: ["vegetative", "tuber_initiation"],
    });
  });

  it("no longer rewrites a single-element group into a bare comparison", () => {
    // The V1 builder collapsed `all_of: [x]` to a flat `x`, quietly
    // editing YAML the author never touched. Round-tripping now leaves
    // the group alone.
    roundTrips({
      all_of: [
        {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -0.5,
        },
      ],
    });
  });

  it("preserves an unparseable AST untouched", () => {
    const original = { op: "approximately", left: { source: "indices" }, right: 0 };
    const parsed = parseConditionTree(original);
    expect(parsed.kind).toBe("unsupported");
    expect(serializeCondition(parsed)).toEqual(original);
  });

  it("preserves a grid anomaly comparison (G-4)", () => {
    roundTrips({
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "flagged_count" },
      right: 5,
    });
  });

  it("preserves a weather_index anomaly comparison (PR-W7)", () => {
    roundTrips({
      op: "gt",
      left: { source: "weather_index", index_code: "evapotranspiration", key: "value" },
      right: 6,
    });
  });

  it("preserves a weather_risk level comparison (PR-R3)", () => {
    roundTrips({
      op: "eq",
      left: { source: "weather_risk", risk_code: "fruit_fly", field: "level" },
      right: "high",
    });
  });

  it("serializes a group built in memory", () => {
    const built: ConditionNode = {
      kind: "group",
      mode: "any",
      children: [
        {
          kind: "term",
          term: {
            op: "lt",
            left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
            right: { kind: "number", value: -0.5 },
          },
        },
        {
          kind: "not",
          child: {
            kind: "term",
            term: {
              op: "in",
              left: { source: "block", field: "growth_stage" },
              values: [{ kind: "string", value: "maturation" }],
            },
          },
        },
      ],
    };
    expect(serializeNode(built)).toEqual({
      any_of: [
        {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -0.5,
        },
        {
          not: {
            op: "in",
            left: { source: "block", field: "growth_stage" },
            values: ["maturation"],
          },
        },
      ],
    });
  });
});

describe("changeTermOp", () => {
  const binary: Term = {
    op: "gt",
    left: { source: "indices", index_code: "ndvi", key: "mean" },
    right: { kind: "number", value: 0.4 },
  };

  it("carries the threshold into `between` instead of discarding it", () => {
    const next = changeTermOp(binary, "between");
    if (next.op !== "between") throw new Error("expected between");
    expect(next.low).toEqual({ kind: "number", value: 0.4 });
    expect(next.high).toEqual({ kind: "number", value: 0.4 });
    expect(next.left).toEqual(binary.left);
  });

  it("carries the threshold into `in` as the first value", () => {
    const next = changeTermOp(binary, "in");
    if (next.op !== "in") throw new Error("expected in");
    expect(next.values).toEqual([{ kind: "number", value: 0.4 }]);
  });

  it("carries the low bound back out of `between`", () => {
    const between = changeTermOp(binary, "between");
    const back = changeTermOp(between, "lt");
    if (back.op === "between" || back.op === "in") throw new Error("expected a binary term");
    expect(back.right).toEqual({ kind: "number", value: 0.4 });
  });

  it("is a no-op when the operator is unchanged", () => {
    expect(changeTermOp(binary, "gt")).toBe(binary);
  });
});
