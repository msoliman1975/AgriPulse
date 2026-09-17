import { describe, expect, it } from "vitest";

import {
  STARTER_BETA_YAML,
  attachBetaNode,
  betaNodeKind,
  buildBetaNode,
  deleteBetaNode,
  dumpBetaDoc,
  edgeKey,
  outgoingEdges,
  parseBetaDoc,
  readCombinations,
  readRegisters,
  reachableFrom,
  referrersOf,
  registeredCodes,
  rewireBetaSlot,
  setBetaNode,
  slotsOf,
  suggestSwitchDefault,
  writeCombinations,
  writeRegisters,
  type BetaTreeDoc,
} from "./betaTree";

/** A small graph with all five kinds and one shared `stop`. */
const YAML = `code: t
registers: [dry, pest_high]
combinations: []
root: cond_1
nodes:
  cond_1:
    condition: { tree: { op: lt, left: { source: indices, index_code: ndmi, key: mean }, right: 0 } }
    on_match: reg_1
    on_miss: set_1
  reg_1:
    register: { code: dry, severity: warning }
    next: set_1
  set_1:
    set: { index_used: ndmi }
    next: sw_1
  sw_1:
    switch:
      on: { source: weather_risk, risk_code: anthracnose, field: score }
      cases:
        - { op: ge, value: 70, go: reg_2 }
      default: stop_1
  reg_2:
    register: { code: pest_high, severity: critical }
    next: stop_1
  stop_1:
    stop: true
`;

function doc(yaml = YAML): BetaTreeDoc {
  const parsed = parseBetaDoc(yaml);
  expect(parsed).not.toBeNull();
  return parsed!;
}

describe("betaNodeKind", () => {
  it("reads the kind off the key that is present, as the engine does", () => {
    const d = doc();
    expect(betaNodeKind(d.nodes!.cond_1)).toBe("condition");
    expect(betaNodeKind(d.nodes!.reg_1)).toBe("register");
    expect(betaNodeKind(d.nodes!.set_1)).toBe("set");
    expect(betaNodeKind(d.nodes!.sw_1)).toBe("switch");
    expect(betaNodeKind(d.nodes!.stop_1)).toBe("stop");
  });

  it("calls a node with none of the keys a condition, which is what a new one is", () => {
    expect(betaNodeKind({})).toBe("condition");
    expect(betaNodeKind(undefined)).toBe("condition");
  });
});

describe("outgoingEdges", () => {
  it("gives a switch its cases in order, then its default", () => {
    const d = doc();
    expect(outgoingEdges(d.nodes!.sw_1)).toEqual([
      { to: "reg_2", kind: "case", caseIndex: 0 },
      { to: "stop_1", kind: "default" },
    ]);
  });

  it("gives a stop nothing", () => {
    expect(outgoingEdges(doc().nodes!.stop_1)).toEqual([]);
  });
});

describe("reachability", () => {
  it("visits a shared node once and terminates on a cycle", () => {
    const cyclic = doc(`root: a
nodes:
  a: { register: { code: x, severity: info }, next: b }
  b: { register: { code: y, severity: info }, next: a }
`);
    expect([...reachableFrom(cyclic, "a")].sort()).toEqual(["a", "b"]);
  });

  it("names every node that points at a target", () => {
    expect(referrersOf(doc(), "stop_1").sort()).toEqual(["reg_2", "sw_1"]);
  });
});

describe("attachBetaNode", () => {
  it("wires the new node into the slot and returns its id", () => {
    const result = attachBetaNode(YAML, {
      parentId: "reg_2",
      slot: { kind: "next" },
      kind: "register",
    });
    const d = doc(result.yaml);
    expect(d.nodes![result.newNodeId]).toBeDefined();
    expect(d.nodes!.reg_2.next).toBe(result.newNodeId);
  });

  it("pre-fills a new switch's default with the node the slot pointed at", () => {
    // reg_2.next was stop_1. Inserting a switch there must keep stop_1 as the
    // fall-through, because that is where the walk was already going.
    const result = attachBetaNode(YAML, {
      parentId: "reg_2",
      slot: { kind: "next" },
      kind: "switch",
    });
    const inserted = doc(result.yaml).nodes![result.newNodeId];
    expect(inserted.switch?.default).toBe("stop_1");
  });

  it("falls back to the tree's only stop when the slot was empty", () => {
    const withGap = YAML.replace("    next: stop_1\n  stop_1:", "  stop_1:");
    const result = attachBetaNode(withGap, {
      parentId: "reg_2",
      slot: { kind: "next" },
      kind: "switch",
    });
    expect(doc(result.yaml).nodes![result.newNodeId].switch?.default).toBe("stop_1");
  });

  it("writes the default key even when it has nothing to suggest", () => {
    // The publish rejects a switch with no default, so the designer must never
    // store one without the key — an empty string is a rejection the author
    // can see, an absent key is one they cannot.
    const node = buildBetaNode("switch");
    expect(node.switch).toHaveProperty("default");
    expect(node.switch?.default).toBe("");
  });

  it("refuses an unknown parent", () => {
    expect(() =>
      attachBetaNode(YAML, { parentId: "nope", slot: { kind: "next" }, kind: "stop" }),
    ).toThrow(/not found/);
  });
});

describe("suggestSwitchDefault", () => {
  it("prefers what the slot already pointed at", () => {
    expect(suggestSwitchDefault(doc(), "reg_2", { kind: "next" }, "stop_1")).toBe("stop_1");
  });

  it("falls back to the parent's other continuation", () => {
    expect(suggestSwitchDefault(doc(), "cond_1", { kind: "match" }, null)).toBe("set_1");
  });

  it("returns empty rather than guessing when two stops exist", () => {
    const twoStops = doc(`root: a
nodes:
  a: { stop: true }
  b: { stop: true }
`);
    expect(suggestSwitchDefault(twoStops, "a", { kind: "next" }, null)).toBe("");
  });
});

describe("deleteBetaNode", () => {
  it("keeps a node the rest of the graph still reaches", () => {
    // reg_2 is deleted; stop_1 survives because sw_1's default still points
    // at it. A tree-shaped cascade would have taken it with it.
    const result = deleteBetaNode(YAML, "reg_2");
    expect(result.removed).toEqual(["reg_2"]);
    expect(doc(result.yaml).nodes!.stop_1).toBeDefined();
  });

  it("removes what only the deleted node could reach", () => {
    const chain = `root: a
nodes:
  a: { register: { code: x, severity: info }, next: b }
  b: { register: { code: y, severity: info }, next: c }
  c: { stop: true }
`;
    const result = deleteBetaNode(chain, "b");
    expect(result.removed.sort()).toEqual(["b", "c"]);
  });

  it("refuses to delete the root", () => {
    expect(() => deleteBetaNode(YAML, "cond_1")).toThrow(/root/);
  });
});

describe("rewireBetaSlot", () => {
  it("repoints one case at another node", () => {
    const next = rewireBetaSlot(YAML, "sw_1", { kind: "case", index: 0 }, "stop_1");
    expect(doc(next).nodes!.sw_1.switch?.cases?.[0].go).toBe("stop_1");
  });

  it("refuses a self-loop", () => {
    expect(() => rewireBetaSlot(YAML, "sw_1", { kind: "default" }, "sw_1")).toThrow(/same node/);
  });
});

describe("slots and edge keys", () => {
  it("gives a switch one slot per case plus the default", () => {
    expect(slotsOf(doc().nodes!.sw_1)).toEqual([{ kind: "case", index: 0 }, { kind: "default" }]);
  });

  it("keys a case edge by its position", () => {
    expect(edgeKey("sw_1", { kind: "case", index: 1 })).toBe("sw_1:case:1");
    expect(edgeKey("sw_1", { kind: "default" })).toBe("sw_1:default");
  });
});

describe("registers and combinations", () => {
  it("reads the declared list and the codes nodes actually register", () => {
    expect(readRegisters(doc())).toEqual(["dry", "pest_high"]);
    expect([...registeredCodes(doc()).entries()].sort()).toEqual([
      ["dry", ["reg_1"]],
      ["pest_high", ["reg_2"]],
    ]);
  });

  it("writes a rule's codes sorted, so one set always has one spelling", () => {
    const next = writeCombinations(YAML, [
      {
        codes: ["pest_high", "dry"],
        action_type: "irrigate",
        status: "issue",
        text_en: "x",
        text_ar: "س",
      },
    ]);
    expect(readCombinations(doc(next))[0].codes).toEqual(["dry", "pest_high"]);
  });

  it("dedupes the registers list", () => {
    expect(readRegisters(doc(writeRegisters(YAML, ["dry", "dry", "new"])))).toEqual(["dry", "new"]);
  });
});

describe("setBetaNode", () => {
  it("replaces a node body and leaves the rest alone", () => {
    const next = setBetaNode(YAML, "reg_1", { register: { code: "dry", severity: "critical" } });
    const d = doc(next);
    expect(d.nodes!.reg_1.register?.severity).toBe("critical");
    expect(d.nodes!.stop_1.stop).toBe(true);
  });
});

describe("STARTER_BETA_YAML", () => {
  it("parses and round-trips", () => {
    const d = parseBetaDoc(STARTER_BETA_YAML);
    expect(d).not.toBeNull();
    expect(parseBetaDoc(dumpBetaDoc(d!))).toEqual(d);
  });
});
