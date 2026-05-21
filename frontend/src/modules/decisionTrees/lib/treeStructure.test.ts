import { describe, expect, it } from "vitest";

import {
  applyAddNode,
  applyDeleteNode,
  applyDeleteUnreachable,
  applyRewireBranch,
  findReferrers,
  findUnreachableNodes,
  generateNodeId,
  parseYamlDoc,
  validateTreeStructure,
} from "./treeStructure";

const BASE_YAML = `code: demo
name_en: Demo
root: root
nodes:
  root:
    label_en: NDVI dropped?
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

describe("generateNodeId", () => {
  it("walks integers until it finds a free slot", () => {
    const doc = parseYamlDoc(BASE_YAML)!;
    expect(generateNodeId(doc, "decision")).toBe("decision_1");
    expect(generateNodeId(doc, "leaf-recommendation")).toBe("leaf_rec_1");
    expect(generateNodeId(doc, "leaf-alert")).toBe("leaf_alert_1");
    expect(generateNodeId(doc, "leaf-noop")).toBe("leaf_noop_1");
  });

  it("skips taken ids", () => {
    const yaml = `${BASE_YAML}  leaf_rec_1:\n    outcome:\n      action_type: spray\n      kind: recommendation\n`;
    const doc = parseYamlDoc(yaml)!;
    expect(generateNodeId(doc, "leaf-recommendation")).toBe("leaf_rec_2");
  });
});

describe("applyAddNode", () => {
  it("rejects adding to an already-filled branch", () => {
    // root.on_match already points at leaf_scout; refuse.
    expect(() =>
      applyAddNode(BASE_YAML, {
        parentId: "root",
        branch: "match",
        kind: "leaf-noop",
      }),
    ).toThrow(/already filled/);
  });

  it("rejects adding under a leaf parent", () => {
    expect(() =>
      applyAddNode(BASE_YAML, {
        parentId: "leaf_scout",
        branch: "match",
        kind: "leaf-noop",
      }),
    ).toThrow(/leaf/);
  });

  it("wires a new node under an empty branch", () => {
    // First clear one branch so we can add to it.
    const cleared = applyDeleteNode(BASE_YAML, "leaf_scout");
    const result = applyAddNode(cleared.yaml, {
      parentId: "root",
      branch: "match",
      kind: "leaf-recommendation",
    });
    const doc = parseYamlDoc(result.yaml)!;
    expect(doc.nodes![result.newNodeId]).toBeDefined();
    expect(doc.nodes!.root.on_match).toBe(result.newNodeId);
    expect(doc.nodes![result.newNodeId].outcome?.kind).toBe("recommendation");
  });
});

describe("applyDeleteNode", () => {
  it("refuses to delete the root", () => {
    expect(() => applyDeleteNode(BASE_YAML, "root")).toThrow(/root/);
  });

  it("removes a leaf and clears the parent pointer", () => {
    const result = applyDeleteNode(BASE_YAML, "leaf_scout");
    expect(result.removed).toEqual(["leaf_scout"]);
    const doc = parseYamlDoc(result.yaml)!;
    expect(doc.nodes!.leaf_scout).toBeUndefined();
    expect(doc.nodes!.root.on_match).toBeUndefined();
    // The other branch stays intact.
    expect(doc.nodes!.root.on_miss).toBe("leaf_noop");
  });

  it("cascades to the whole subtree", () => {
    // Build a 3-level tree: root → mid → leaf_a / leaf_b
    const yaml = `code: t
root: root
nodes:
  root:
    label_en: top
    on_match: mid
    on_miss: tail
  mid:
    label_en: mid
    on_match: leaf_a
    on_miss: leaf_b
  leaf_a:
    outcome: { action_type: scout, kind: recommendation, text_en: a }
  leaf_b:
    outcome: { action_type: scout, kind: recommendation, text_en: b }
  tail:
    outcome: { action_type: no_action, text_en: ok }
`;
    const result = applyDeleteNode(yaml, "mid");
    expect(result.removed.sort()).toEqual(["leaf_a", "leaf_b", "mid"]);
    const doc = parseYamlDoc(result.yaml)!;
    expect(doc.nodes!.mid).toBeUndefined();
    expect(doc.nodes!.leaf_a).toBeUndefined();
    expect(doc.nodes!.leaf_b).toBeUndefined();
    expect(doc.nodes!.tail).toBeDefined();
  });
});

describe("applyRewireBranch", () => {
  it("repoints an existing branch at a different node", () => {
    const result = applyRewireBranch(BASE_YAML, {
      parentId: "root",
      branch: "match",
      toNodeId: "leaf_noop",
    });
    const doc = parseYamlDoc(result)!;
    expect(doc.nodes!.root.on_match).toBe("leaf_noop");
    // Old target survives — orphan cleanup is the author's job.
    expect(doc.nodes!.leaf_scout).toBeDefined();
  });

  it("rejects a self-loop", () => {
    expect(() =>
      applyRewireBranch(BASE_YAML, {
        parentId: "root",
        branch: "match",
        toNodeId: "root",
      }),
    ).toThrow(/same node/);
  });

  it("rejects an unknown target", () => {
    expect(() =>
      applyRewireBranch(BASE_YAML, {
        parentId: "root",
        branch: "match",
        toNodeId: "ghost",
      }),
    ).toThrow(/not found/);
  });

  it("rejects rewiring from a leaf parent", () => {
    expect(() =>
      applyRewireBranch(BASE_YAML, {
        parentId: "leaf_scout",
        branch: "match",
        toNodeId: "leaf_noop",
      }),
    ).toThrow(/leaf/);
  });
});

describe("findUnreachableNodes", () => {
  it("returns empty when every node is reachable", () => {
    expect(findUnreachableNodes(BASE_YAML)).toEqual([]);
  });

  it("flags a node that was unwired via rewire", () => {
    // Rewire root.match away from leaf_scout to leaf_noop — that
    // leaves leaf_scout orphaned.
    const rewired = applyRewireBranch(BASE_YAML, {
      parentId: "root",
      branch: "match",
      toNodeId: "leaf_noop",
    });
    expect(findUnreachableNodes(rewired)).toEqual(["leaf_scout"]);
  });
});

describe("applyDeleteUnreachable", () => {
  it("removes orphans + keeps reachable nodes intact", () => {
    const rewired = applyRewireBranch(BASE_YAML, {
      parentId: "root",
      branch: "match",
      toNodeId: "leaf_noop",
    });
    const cleaned = applyDeleteUnreachable(rewired);
    const doc = parseYamlDoc(cleaned)!;
    expect(Object.keys(doc.nodes!).sort()).toEqual(["leaf_noop", "root"]);
  });

  it("is a no-op when the tree has no orphans", () => {
    const out = applyDeleteUnreachable(BASE_YAML);
    const doc = parseYamlDoc(out)!;
    expect(Object.keys(doc.nodes!).sort()).toEqual([
      "leaf_noop",
      "leaf_scout",
      "root",
    ]);
  });
});

describe("findReferrers", () => {
  it("lists nodes that point at the target", () => {
    const doc = parseYamlDoc(BASE_YAML)!;
    expect(findReferrers(doc, "leaf_scout")).toEqual(["root"]);
    expect(findReferrers(doc, "leaf_noop")).toEqual(["root"]);
    expect(findReferrers(doc, "root")).toEqual([]);
  });
});

describe("validateTreeStructure", () => {
  it("is clean on a complete tree", () => {
    expect(validateTreeStructure(BASE_YAML)).toEqual([]);
  });

  it("flags a decision missing children", () => {
    const partial = `code: x
root: root
nodes:
  root:
    label_en: top
`;
    const errors = validateTreeStructure(partial);
    const messages = errors.map((e) => e.message);
    expect(messages).toContain("Decision is missing `on_match` child.");
    expect(messages).toContain("Decision is missing `on_miss` child.");
  });

  it("flags a dangling pointer", () => {
    const partial = `code: x
root: root
nodes:
  root:
    on_match: ghost
    on_miss: leaf
  leaf:
    outcome: { action_type: scout, kind: recommendation, text_en: ok }
`;
    const errors = validateTreeStructure(partial);
    expect(errors.some((e) => e.message.includes("ghost"))).toBe(true);
  });
});
