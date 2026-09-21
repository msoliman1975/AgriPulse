import { describe, expect, it } from "vitest";

import type { TreePathStepDTO } from "@/api/decisionTrees";

import {
  formatValue,
  registeredDetail,
  walkHighlight,
  walkStepsFromDryRun,
  walkStepsFromTrace,
  writtenNames,
  type DryRunWalkStep,
  type WalkStep,
} from "./walkTrace";

function dryRunStep(over: Partial<DryRunWalkStep> = {}): DryRunWalkStep {
  return {
    node_id: "n1",
    kind: "condition",
    matched: true,
    label_en: "Is the soil dry?",
    label_ar: null,
    values: { "indices.smi.mean": 0.12 },
    detail: null,
    ...over,
  };
}

function step(over: Partial<WalkStep> = {}): WalkStep {
  return {
    nodeId: "n1",
    kind: "condition",
    matched: true,
    labelEn: null,
    labelAr: null,
    values: {},
    detail: null,
    ...over,
  };
}

describe("walkStepsFromDryRun", () => {
  it("reads the server's own fields straight through", () => {
    const [read] = walkStepsFromDryRun([dryRunStep()]);
    expect(read.nodeId).toBe("n1");
    expect(read.kind).toBe("condition");
    expect(read.matched).toBe(true);
    expect(read.values).toEqual({ "indices.smi.mean": 0.12 });
  });

  it("answers with an empty list when the field is missing", () => {
    // The dry run panel took the whole page down on a field the server did
    // not send. Nothing here may repeat that.
    expect(walkStepsFromDryRun(undefined)).toEqual([]);
    expect(walkStepsFromDryRun(null)).toEqual([]);
  });

  it("calls a kind it does not know unknown rather than dropping the step", () => {
    const [read] = walkStepsFromDryRun([dryRunStep({ kind: "somethingelse" })]);
    expect(read.kind).toBe("unknown");
    expect(read.nodeId).toBe("n1");
  });
});

describe("walkStepsFromTrace", () => {
  function traceStep(values: Record<string, unknown>): TreePathStepDTO {
    return { node_id: "n2", matched: null, label_en: "Low vigour", label_ar: null, values };
  }

  it("lifts kind and detail back out of the packed values map", () => {
    // `service._folding_path_steps` packs both inside `values`, because
    // `node_path` is free-form JSONB and had nowhere else to put them.
    const [read] = walkStepsFromTrace([
      traceStep({
        kind: "register",
        detail: { code: "dry", severity: "warning" },
        "indices.smi.mean": 0.12,
      }),
    ]);
    expect(read.kind).toBe("register");
    expect(read.detail).toEqual({ code: "dry", severity: "warning" });
    expect(read.values).toEqual({ "indices.smi.mean": 0.12 });
  });

  it("does not leave kind or detail behind in the values", () => {
    const [read] = walkStepsFromTrace([traceStep({ kind: "stop", detail: null })]);
    expect(read.values).toEqual({});
  });

  it("reads an old-engine row as an unknown kind rather than dropping it", () => {
    const [read] = walkStepsFromTrace([traceStep({ "indices.ndvi.mean": 0.4 })]);
    expect(read.kind).toBe("unknown");
    expect(read.values).toEqual({ "indices.ndvi.mean": 0.4 });
  });
});

describe("walkHighlight", () => {
  it("takes the match branch of a condition that matched", () => {
    const { edges } = walkHighlight([
      step({ nodeId: "a", matched: true }),
      step({ nodeId: "b", kind: "stop", matched: null }),
    ]);
    expect([...edges]).toEqual(["a:match"]);
  });

  it("takes the miss branch of a condition that did not", () => {
    const { edges } = walkHighlight([
      step({ nodeId: "a", matched: false }),
      step({ nodeId: "b", kind: "stop", matched: null }),
    ]);
    expect([...edges]).toEqual(["a:miss"]);
  });

  it("reads a switch's chosen case off the step, not off the tree", () => {
    // Two cases can point at the same node. Matching the next step's id
    // against the node's slots would then pick whichever came first.
    const { edges } = walkHighlight([
      step({ nodeId: "s", kind: "switch", matched: null, detail: { case: 2, went_to: "b" } }),
      step({ nodeId: "b", kind: "stop", matched: null }),
    ]);
    expect([...edges]).toEqual(["s:case:2"]);
  });

  it("reads a null case as the switch's default", () => {
    const { edges } = walkHighlight([
      step({ nodeId: "s", kind: "switch", matched: null, detail: { case: null, went_to: "b" } }),
      step({ nodeId: "b", kind: "stop", matched: null }),
    ]);
    expect([...edges]).toEqual(["s:default"]);
  });

  it("marks the register nodes apart from the rest of the route", () => {
    const { nodes, registerNodes, stopNodeId } = walkHighlight([
      step({ nodeId: "a" }),
      step({ nodeId: "r", kind: "register", matched: null, detail: { code: "dry" } }),
      step({ nodeId: "end", kind: "stop", matched: null }),
    ]);
    expect([...nodes]).toEqual(["a", "r", "end"]);
    expect([...registerNodes]).toEqual(["r"]);
    expect(stopNodeId).toBe("end");
  });

  it("names the node a failed walk died on, and finds no stop", () => {
    // A walk that errored never reached a stop node, so the tree never said
    // it was finished. The last node reached is the whole answer to where it
    // fell over.
    const { stopNodeId, errorNodeId } = walkHighlight([
      step({ nodeId: "a" }),
      step({ nodeId: "s", kind: "switch", matched: null, detail: { case: null } }),
    ]);
    expect(stopNodeId).toBeNull();
    expect(errorNodeId).toBe("s");
  });

  it("never draws an edge out of the last step", () => {
    // On a failure the pointer it was about to follow is the thing that did
    // not work, so drawing it would assert an edge that does not exist.
    const { edges } = walkHighlight([step({ nodeId: "a", kind: "register", matched: null })]);
    expect(edges.size).toBe(0);
  });

  it("is empty for an empty walk", () => {
    const highlight = walkHighlight([]);
    expect(highlight.nodes.size).toBe(0);
    expect(highlight.stopNodeId).toBeNull();
    expect(highlight.errorNodeId).toBeNull();
  });
});

describe("registeredDetail", () => {
  it("reads the code, the severity and whether the severity rose", () => {
    const read = registeredDetail(
      step({
        kind: "register",
        matched: null,
        detail: { code: "dry", severity: "critical", repeat: true, raised: true },
      }),
    );
    expect(read).toEqual({ code: "dry", severity: "critical", repeat: true, raised: true });
  });

  it("is null on a step that is not a register", () => {
    expect(registeredDetail(step())).toBeNull();
  });

  it("is null on a register whose detail has no code", () => {
    expect(registeredDetail(step({ kind: "register", matched: null, detail: {} }))).toBeNull();
  });
});

describe("writtenNames", () => {
  it("lists the variables a set step wrote, in order", () => {
    const names = writtenNames(
      step({ kind: "set", matched: null, detail: { wrote: { vigour: "low", water: 0.2 } } }),
    );
    expect(names).toEqual(["vigour", "water"]);
  });

  it("is empty on a step that wrote nothing", () => {
    expect(writtenNames(step())).toEqual([]);
  });
});

describe("formatValue", () => {
  it("cuts a reading to three decimals", () => {
    expect(formatValue(0.3142857142857143, "—")).toBe("0.314");
  });

  it("leaves a whole number alone", () => {
    expect(formatValue(12, "—")).toBe("12");
  });

  it("says absent in words rather than showing an empty cell", () => {
    // Why a condition went the way it did is often "the tree could not read
    // this", and a blank cell reads as a rendering fault instead.
    expect(formatValue(null, "no reading")).toBe("no reading");
    expect(formatValue(undefined, "no reading")).toBe("no reading");
  });

  it("joins a list and keeps a boolean", () => {
    expect(formatValue([1, 2], "—")).toBe("1, 2");
    expect(formatValue(false, "—")).toBe("false");
  });
});
