import { describe, expect, it } from "vitest";

import type { TreePathStepDTO } from "@/api/decisionTrees";

import { pathHighlight } from "./dryRunHighlight";

function step(
  nodeId: string,
  matched: boolean | null = null,
): TreePathStepDTO {
  return { node_id: nodeId, matched, label_en: null, label_ar: null, values: {} };
}

describe("pathHighlight", () => {
  it("collects every visited node", () => {
    const r = pathHighlight([step("root", true), step("mid", false), step("leaf")]);
    expect([...r.nodes].sort()).toEqual(["leaf", "mid", "root"]);
    expect(r.terminalNodeId).toBe("leaf");
  });

  it("derives match-edge for matched=true", () => {
    const r = pathHighlight([step("root", true), step("leaf")]);
    expect([...r.edges]).toEqual(["root->leaf-match"]);
  });

  it("derives miss-edge for matched=false", () => {
    const r = pathHighlight([step("root", false), step("leaf")]);
    expect([...r.edges]).toEqual(["root->leaf-miss"]);
  });

  it("doesn't emit an edge from a leaf step (matched=null)", () => {
    const r = pathHighlight([step("only_leaf")]);
    expect(r.edges.size).toBe(0);
  });

  it("chains multiple steps correctly", () => {
    const r = pathHighlight([
      step("root", true),
      step("mid", false),
      step("leaf"),
    ]);
    expect([...r.edges].sort()).toEqual(["mid->leaf-miss", "root->mid-match"]);
  });
});
