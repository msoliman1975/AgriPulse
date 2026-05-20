import { describe, expect, it } from "vitest";

import {
  applyEditsToYaml,
  hasEdits,
  patchBuffer,
  type NodeEditBuffer,
} from "./treeEdit";

const _BASE_YAML = `code: demo
name_en: Demo
root: root
nodes:
  root:
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -0.15
    on_match: leaf_scout
    on_miss: leaf_noop
    label_en: NDVI dropped?
  leaf_scout:
    outcome:
      action_type: scout
      kind: recommendation
      confidence: 0.7
      text_en: Scout for stress
  leaf_noop:
    outcome:
      action_type: no_action
      text_en: ok
`;

describe("patchBuffer", () => {
  it("merges patches without losing prior outcome fields", () => {
    const initial: NodeEditBuffer = {};
    const after1 = patchBuffer(initial, "leaf_scout", {
      outcome: { text_en: "new text" },
    });
    const after2 = patchBuffer(after1, "leaf_scout", {
      outcome: { confidence: 0.9 },
    });
    expect(after2.leaf_scout?.outcome).toEqual({
      text_en: "new text",
      confidence: 0.9,
    });
  });

  it("merges label patches alongside outcome patches without clobbering either", () => {
    const buf = patchBuffer(
      patchBuffer({}, "n1", { label_en: "Label A" }),
      "n1",
      { outcome: { action_type: "scout" } },
    );
    expect(buf.n1?.label_en).toBe("Label A");
    expect(buf.n1?.outcome?.action_type).toBe("scout");
  });
});

describe("hasEdits", () => {
  it("reports false for an empty buffer and one full of empty patches", () => {
    expect(hasEdits({})).toBe(false);
    expect(hasEdits({ n1: {} })).toBe(false);
  });
  it("reports true when at least one patch has a field", () => {
    expect(hasEdits({ n1: { label_en: "x" } })).toBe(true);
  });
});

describe("applyEditsToYaml", () => {
  it("patches a leaf's text_en and keeps the surrounding tree intact", () => {
    const out = applyEditsToYaml(_BASE_YAML, {
      leaf_scout: { outcome: { text_en: "Updated scout text" } },
    });
    expect(out).toContain("Updated scout text");
    // The other nodes are still present.
    expect(out).toContain("leaf_noop");
    expect(out).toContain("on_match");
  });

  it("flipping kind: recommendation → alert drops confidence and adds severity", () => {
    const out = applyEditsToYaml(_BASE_YAML, {
      leaf_scout: { outcome: { kind: "alert", severity: "critical" } },
    });
    // confidence must be gone because alert leaves don't carry it; the
    // loader's compile_tree would have rejected an alert leaf with
    // confidence + missing severity.
    expect(out).not.toMatch(/leaf_scout:[\s\S]*?confidence/);
    expect(out).toContain("severity: critical");
    expect(out).toContain("kind: alert");
  });

  it("flipping kind: alert → recommendation drops severity", () => {
    const alertYaml = applyEditsToYaml(_BASE_YAML, {
      leaf_scout: { outcome: { kind: "alert", severity: "warning" } },
    });
    const out = applyEditsToYaml(alertYaml, {
      leaf_scout: { outcome: { kind: "recommendation", confidence: 0.8 } },
    });
    expect(out).not.toMatch(/leaf_scout:[\s\S]*?severity/);
    expect(out).toContain("confidence: 0.8");
  });

  it("patches label_en on a decision node without disturbing its condition", () => {
    const out = applyEditsToYaml(_BASE_YAML, {
      root: { label_en: "Has the NDVI dropped significantly?" },
    });
    expect(out).toContain("Has the NDVI dropped significantly?");
    // Condition still intact
    expect(out).toContain("baseline_deviation");
    expect(out).toContain("op: lt");
  });

  it("skips patches for unknown node ids without dropping the rest", () => {
    const out = applyEditsToYaml(_BASE_YAML, {
      not_a_real_node: { label_en: "phantom" },
      leaf_scout: { outcome: { text_en: "kept" } },
    });
    expect(out).not.toContain("phantom");
    expect(out).toContain("kept");
  });

  it("returns the input verbatim when the YAML has no nodes block (defensive)", () => {
    const malformed = "code: x\nname_en: y\n";
    expect(applyEditsToYaml(malformed, { root: { label_en: "x" } })).toBe(malformed);
  });
});
