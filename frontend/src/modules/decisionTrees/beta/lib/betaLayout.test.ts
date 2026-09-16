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
      switch: { cases: [{ op: "ge", value: 1, go: "x" }], default: "y" },
    });
    const three = betaNodeHeight({
      switch: {
        cases: [
          { op: "ge", value: 1, go: "x" },
          { op: "ge", value: 2, go: "x" },
          { op: "ge", value: 3, go: "x" },
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
