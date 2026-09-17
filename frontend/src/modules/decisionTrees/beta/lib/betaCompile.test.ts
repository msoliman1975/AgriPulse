import { describe, expect, it } from "vitest";

import { betaEditorHints, hasEditorHints, type EditorHint } from "./betaCompile";

/**
 * The hints, read by the sentence they render rather than by the compiler
 * rule they map to. Three different mistakes share the rule `unknown-target`
 * — see `EditorHint.messageKey` — and a test that read the rule could not
 * tell "you left the miss branch empty" from "the default points at a node
 * that is gone".
 */

const KNOWN = ["dry", "pest_high", "ndvi_low"];

function messages(yaml: string, known: string[] = KNOWN): string[] {
  return betaEditorHints({ yaml, knownFindingCodes: known }).map((h) => h.messageKey);
}

function hints(yaml: string, known: string[] = KNOWN): EditorHint[] {
  return betaEditorHints({ yaml, knownFindingCodes: known });
}

const CLEAN = `registers: [dry]
combinations: []
root: cond_1
nodes:
  cond_1:
    condition: { tree: { op: lt, left: { source: indices, index_code: ndmi, key: mean }, right: 0 } }
    on_match: reg_1
    on_miss: stop_1
  reg_1:
    register: { code: dry, severity: warning }
    next: stop_1
  stop_1:
    stop: true
`;

describe("betaEditorHints", () => {
  it("accepts a tree where every route reaches stop and every code resolves", () => {
    expect(hints(CLEAN)).toEqual([]);
    expect(hasEditorHints([])).toBe(false);
  });

  it("rejects YAML that does not parse", () => {
    expect(messages("nodes: [unterminated")).toEqual(["yaml_unparsed"]);
  });

  it("rejects a switch with no default, and names the node", () => {
    const yaml = `registers: []
root: sw_1
nodes:
  sw_1:
    switch:
      on: { source: weather_risk, risk_code: anthracnose, field: score }
      cases: [{ op: ge, value: 70, go: stop_1 }]
  stop_1:
    stop: true
`;
    const found = hints(yaml);
    const hint = found.find((h) => h.messageKey === "switch_without_default");
    expect(hint).toBeDefined();
    expect(hint!.rule).toBe("switch-without-default");
    expect(hint!.node_id).toBe("sw_1");
    expect(hint!.edge_key).toBe("sw_1:default");
  });

  it("rejects a default that points at nothing", () => {
    const yaml = CLEAN.replace(
      "  stop_1:\n    stop: true\n",
      `  sw_1:
    switch:
      on: { source: block, field: growth_stage }
      cases: [{ op: eq, value: a, go: stop_1 }]
      default: ghost
  stop_1:
    stop: true
`,
    );
    expect(messages(yaml)).toContain("switch_default_unknown");
  });

  it("rejects a register node whose code the tree does not declare", () => {
    const yaml = CLEAN.replace("registers: [dry]", "registers: []");
    expect(messages(yaml)).toContain("register_not_declared");
  });

  it("rejects a code that is in no catalogue, from the node and from the list", () => {
    const found = hints(CLEAN, []);
    const unknown = found.filter((h) => h.messageKey === "register_unknown_code");
    expect(unknown).toHaveLength(2);
    expect(unknown.map((h) => h.node_id).sort()).toEqual([null, "reg_1"]);
  });

  it("names every node from which no route reaches stop", () => {
    const yaml = `registers: []
root: a
nodes:
  a: { register: { code: x, severity: info }, next: b }
  b: { register: { code: x, severity: info }, next: a }
`;
    const found = hints(yaml, ["x"]);
    const unreached = found.filter((h) => h.messageKey === "unreached_stop").map((h) => h.node_id);
    expect(unreached.sort()).toEqual(["a", "b"]);
  });

  it("names a node the root cannot reach", () => {
    const yaml = `${CLEAN}  orphan:\n    stop: true\n`;
    expect(hints(yaml).map((h) => [h.messageKey, h.node_id])).toContainEqual([
      "unreachable_node",
      "orphan",
    ]);
  });

  it("rejects an empty pointer and a dangling one separately", () => {
    const empty = CLEAN.replace("    on_miss: stop_1\n", "");
    expect(messages(empty)).toContain("empty_slot");
    const dangling = CLEAN.replace("on_miss: stop_1", "on_miss: ghost");
    expect(messages(dangling)).toContain("dangling_pointer");
  });

  it("rejects an old-style outcome leaf in a folding tree", () => {
    const yaml = CLEAN.replace(
      "  stop_1:\n    stop: true\n",
      "  stop_1:\n    stop: true\n    outcome: { action_type: scout }\n",
    );
    expect(messages(yaml)).toContain("mixed_leaf_kinds");
  });

  it("rejects two rules that match the same set, whatever order the codes are in", () => {
    const yaml = `registers: [dry, pest_high]
combinations:
  - codes: [dry, pest_high]
    action_type: scout
    status: issue
    text_en: a
    text_ar: أ
  - codes: [pest_high, dry]
    action_type: spray
    status: alert
    text_en: b
    text_ar: ب
root: stop_1
nodes:
  stop_1: { stop: true }
`;
    const dup = hints(yaml).find((h) => h.messageKey === "duplicate_combination");
    expect(dup).toBeDefined();
    expect(dup!.rule).toBe("combination-duplicate-set");
    expect(dup!.params).toMatchObject({ position: 2, first: 1 });
  });

  it("rejects a rule naming a code the tree never registers", () => {
    const yaml = `registers: [dry]
combinations:
  - codes: [ndvi_low]
    action_type: scout
    status: issue
    text_en: a
    text_ar: أ
root: stop_1
nodes:
  stop_1: { stop: true }
`;
    expect(messages(yaml)).toContain("combination_unknown_code");
  });

  it("flags a body with nothing in it", () => {
    expect(hasEditorHints(hints("root: x\nnodes: {}\n", []))).toBe(true);
  });
});
