import { describe, expect, it } from "vitest";

import { BETA_LAYOUT, betaNodeHeight, layoutBetaTree } from "./betaLayout";
import { parseBetaDoc } from "./betaTree";

const YAML = `root: cond_1
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

describe("layoutBetaTree", () => {
  it("places a shared node once, not once per route", () => {
    // Both routes end at stop_1. The binary tree layout would draw two boxes
    // with one id; this must draw one.
    const layout = layoutBetaTree(parseBetaDoc(YAML));
    expect(layout.nodes.filter((n) => n.id === "stop_1")).toHaveLength(1);
    expect(layout.nodes).toHaveLength(3);
  });

  it("gives every edge a downward direction by taking the longest route", () => {
    const layout = layoutBetaTree(parseBetaDoc(YAML));
    // stop_1 is one hop from the root and two through reg_1, so it sits below
    // reg_1 and both edges point down.
    for (const edge of layout.edges) {
      expect(edge.toY).toBeGreaterThan(edge.fromY);
    }
  });

  it("draws one edge per outgoing pointer, keyed by slot", () => {
    const layout = layoutBetaTree(parseBetaDoc(YAML));
    expect(layout.edges.map((e) => e.key).sort()).toEqual([
      "cond_1:match",
      "cond_1:miss",
      "reg_1:next",
    ]);
  });

  it("fans two edges out of one node to different departure points", () => {
    const layout = layoutBetaTree(parseBetaDoc(YAML));
    const fromRoot = layout.edges.filter((e) => e.from === "cond_1");
    expect(fromRoot[0].fromX).not.toBe(fromRoot[1].fromX);
  });

  it("returns an empty result for a body with no usable root", () => {
    expect(layoutBetaTree(parseBetaDoc("nodes: {}\n")).nodes).toEqual([]);
    expect(layoutBetaTree(null).nodes).toEqual([]);
  });

  it("draws a node with three parents once, below all three", () => {
    // The known issue on this branch was that a shared `stop` is drawn twice.
    // `layout/treeLayout.ts` does that — it walks a strict binary tree and
    // re-places a shared child once per parent — which is why the beta canvas
    // reads this module instead. A folding tree funnels many routes into one
    // fold, so the shared node is the normal case, not the exception.
    const diamond = parseBetaDoc(`root: sw_1
nodes:
  sw_1:
    switch:
      on: { source: block, field: growth_stage }
      cases:
        - { op: eq, value: a, go: reg_1 }
        - { op: eq, value: b, go: reg_2 }
      default: stop_1
  reg_1: { register: { code: dry, severity: info }, next: stop_1 }
  reg_2: { register: { code: dry, severity: info }, next: stop_1 }
  stop_1: { stop: true }
`);
    const layout = layoutBetaTree(diamond);
    expect(layout.nodes.filter((n) => n.id === "stop_1")).toHaveLength(1);
    expect(layout.nodes).toHaveLength(4);
    expect(layout.byId.size).toBe(4);

    // Three pointers, three edges, one box. Each one arrives at the same
    // place, and each one points down.
    const intoStop = layout.edges.filter((e) => e.to === "stop_1");
    expect(intoStop).toHaveLength(3);
    for (const edge of intoStop) {
      expect(edge.toX).toBe(layout.byId.get("stop_1")!.x + BETA_LAYOUT.NODE_WIDTH / 2);
      expect(edge.toY).toBeGreaterThan(edge.fromY);
    }
  });

  it("lays out a cycle instead of hanging", () => {
    const cyclic = parseBetaDoc(`root: a
nodes:
  a: { register: { code: x, severity: info }, next: b }
  b: { register: { code: x, severity: info }, next: a }
`);
    expect(layoutBetaTree(cyclic).nodes).toHaveLength(2);
  });
});

describe("betaNodeHeight", () => {
  it("grows a switch box with its cases, so the bands are readable in the body", () => {
    const one = betaNodeHeight({
      switch: { cases: [{ ge: 1, go: "x" }], default: "y" },
    });
    const three = betaNodeHeight({
      switch: {
        cases: [
          { ge: 1, go: "x" },
          { ge: 2, go: "x" },
          { ge: 3, go: "x" },
        ],
        default: "y",
      },
    });
    expect(three - one).toBe(2 * BETA_LAYOUT.SWITCH_ROW_HEIGHT);
  });

  it("leaves every other kind at the base height", () => {
    expect(betaNodeHeight({ stop: true })).toBe(BETA_LAYOUT.NODE_HEIGHT);
    expect(betaNodeHeight({ register: { code: "x", severity: "info" } })).toBe(
      BETA_LAYOUT.NODE_HEIGHT,
    );
  });
});
