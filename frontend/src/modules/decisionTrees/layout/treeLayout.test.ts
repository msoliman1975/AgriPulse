import { describe, expect, it } from "vitest";

import { layoutTree, type CompiledTree } from "./treeLayout";

describe("layoutTree", () => {
  it("returns an empty result for a missing or malformed compiled body", () => {
    expect(layoutTree(null).nodes).toEqual([]);
    expect(layoutTree(undefined).nodes).toEqual([]);
    // Root pointing at a node that doesn't exist → empty (caller renders empty-state).
    expect(layoutTree({ root: "missing", nodes: {} }).nodes).toEqual([]);
  });

  it("positions a single-leaf tree at the origin row", () => {
    const compiled: CompiledTree = {
      root: "leaf",
      nodes: {
        leaf: { outcome: { action_type: "scout", text_en: "x" } },
      },
    };
    const result = layoutTree(compiled);
    expect(result.nodes).toHaveLength(1);
    expect(result.nodes[0].id).toBe("leaf");
    expect(result.nodes[0].role).toBe("leaf-recommendation");
    expect(result.edges).toEqual([]);
  });

  it("distinguishes alert leaves from recommendation leaves by outcome.kind", () => {
    const compiled: CompiledTree = {
      root: "root",
      nodes: {
        root: {
          on_match: "alertLeaf",
          on_miss: "recLeaf",
        },
        alertLeaf: {
          outcome: { kind: "alert", action_type: "inspect", text_en: "warn", severity: "critical" },
        },
        recLeaf: { outcome: { kind: "recommendation", action_type: "scout", text_en: "x" } },
      },
    };
    const roles = Object.fromEntries(layoutTree(compiled).nodes.map((n) => [n.id, n.role]));
    expect(roles.alertLeaf).toBe("leaf-alert");
    expect(roles.recLeaf).toBe("leaf-recommendation");
  });

  it("classifies no_action leaves separately so they render dim", () => {
    const compiled: CompiledTree = {
      root: "leaf",
      nodes: {
        leaf: { outcome: { action_type: "no_action", text_en: "ok" } },
      },
    };
    expect(layoutTree(compiled).nodes[0].role).toBe("leaf-noop");
  });

  it("places on_match child to the left of on_miss child at the next depth", () => {
    const compiled: CompiledTree = {
      root: "root",
      nodes: {
        root: { on_match: "matchLeaf", on_miss: "missLeaf" },
        matchLeaf: { outcome: { action_type: "scout", text_en: "m" } },
        missLeaf: { outcome: { action_type: "scout", text_en: "n" } },
      },
    };
    const result = layoutTree(compiled);
    const byId = Object.fromEntries(result.nodes.map((n) => [n.id, n]));
    expect(byId.matchLeaf.x).toBeLessThan(byId.missLeaf.x);
    expect(byId.matchLeaf.y).toBeGreaterThan(byId.root.y); // deeper row
  });

  it("emits one edge per non-leaf branch with the correct branch tag", () => {
    const compiled: CompiledTree = {
      root: "root",
      nodes: {
        root: { on_match: "matchLeaf", on_miss: "missLeaf" },
        matchLeaf: { outcome: { action_type: "scout", text_en: "m" } },
        missLeaf: { outcome: { action_type: "scout", text_en: "n" } },
      },
    };
    const edges = layoutTree(compiled).edges;
    expect(edges).toHaveLength(2);
    const matchEdge = edges.find((e) => e.to === "matchLeaf");
    const missEdge = edges.find((e) => e.to === "missLeaf");
    expect(matchEdge?.branch).toBe("match");
    expect(missEdge?.branch).toBe("miss");
  });

  it("does not blow the stack on a cycle (malformed compiled body)", () => {
    const compiled: CompiledTree = {
      root: "a",
      nodes: {
        a: { on_match: "b", on_miss: "b" },
        b: { on_match: "a", on_miss: "a" }, // cycle
      },
    };
    // We don't pin the exact result; we just need not to recurse infinitely.
    const result = layoutTree(compiled);
    expect(result.nodes.length).toBeGreaterThan(0);
  });
});
