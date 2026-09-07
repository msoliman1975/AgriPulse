import jsYaml from "js-yaml";
import { describe, expect, it } from "vitest";

import { layoutTree, type CompiledTree } from "../layout/treeLayout";
import { applyEditsToYaml } from "./treeEdit";
import { buildNodeBody } from "./treeStructure";

const YAML = `
code: probe_v1
name_en: Probe
root: root
nodes:
  root:
    condition:
      tree: { op: lt, left: { source: indices, index_code: ndvi, key: mean }, right: 0.4 }
    on_match: leaf_a
    on_miss: leaf_b
  leaf_a:
    outcome:
      kind: recommendation
      action_type: scout
      confidence: 0.7
      text_en: Go and look.
  leaf_b:
    outcome:
      kind: alert
      action_type: scout
      severity: warning
      text_en: Pest pressure.
`;

function outcomeAfter(nodeId: string, patch: Record<string, unknown>): Record<string, unknown> {
  const next = applyEditsToYaml(YAML, { [nodeId]: { outcome: patch } });
  const doc = jsYaml.load(next) as {
    nodes: Record<string, { outcome: Record<string, unknown> }>;
  };
  return doc.nodes[nodeId].outcome;
}

describe("switching a leaf's kind rewrites the YAML coherently", () => {
  it("a recommendation becoming a status drops action type and confidence", () => {
    // The loader refuses a `status` on anything but a status leaf, and a
    // status leaf ranks itself by its code rather than by a severity. Left
    // behind, those fields would publish a leaf that says two things.
    const outcome = outcomeAfter("leaf_a", { kind: "status" });

    expect(outcome).toEqual({
      kind: "status",
      status: "good",
      text_en: "Go and look.",
    });
  });

  it("an alert becoming a status drops the severity", () => {
    const outcome = outcomeAfter("leaf_b", { kind: "status" });

    expect(outcome.severity).toBeUndefined();
    expect(outcome.status).toBe("good");
  });

  it("a status the author picked is kept", () => {
    const outcome = outcomeAfter("leaf_a", { kind: "status", status: "very_good" });

    expect(outcome.status).toBe("very_good");
  });

  it("a status becoming an alert drops the status code", () => {
    const first = applyEditsToYaml(YAML, {
      leaf_a: { outcome: { kind: "status", status: "issue" } },
    });
    const second = applyEditsToYaml(first, {
      leaf_a: { outcome: { kind: "alert", action_type: "scout", severity: "critical" } },
    });
    const doc = jsYaml.load(second) as {
      nodes: Record<string, { outcome: Record<string, unknown> }>;
    };

    expect(doc.nodes.leaf_a.outcome.status).toBeUndefined();
    expect(doc.nodes.leaf_a.outcome.severity).toBe("critical");
  });

  it("becoming a no-action leaf writes both spellings and drops the rest", () => {
    const outcome = outcomeAfter("leaf_b", { kind: "no_action" });

    expect(outcome.kind).toBe("no_action");
    // Every tree published before the four kinds existed carries only
    // `action_type`, and the loader reads either, so both are written.
    expect(outcome.action_type).toBe("no_action");
    expect(outcome.severity).toBeUndefined();
    expect(outcome.status).toBeUndefined();
  });
});

describe("a new node of each kind", () => {
  it("a status node carries a code and no severity, confidence or action type", () => {
    const body = buildNodeBody("leaf-status") as { outcome: Record<string, unknown> };

    expect(body.outcome.kind).toBe("status");
    expect(body.outcome.status).toBe("good");
    expect(body.outcome.action_type).toBeUndefined();
    expect(body.outcome.severity).toBeUndefined();
    expect(body.outcome.confidence).toBeUndefined();
  });

  it("a no-action node no longer claims to be a recommendation", () => {
    // It used to be written as `kind: recommendation` with
    // `action_type: no_action`, which is the shape that made 15 shipped
    // leaves read as amber recommendations.
    const body = buildNodeBody("leaf-noop") as { outcome: Record<string, unknown> };

    expect(body.outcome.kind).toBe("no_action");
    expect(body.outcome.action_type).toBe("no_action");
  });
});

describe("the canvas tells the four kinds apart", () => {
  function roleOf(outcome: Record<string, unknown>): string {
    const compiled: CompiledTree = { root: "leaf", nodes: { leaf: { outcome } } };
    return layoutTree(compiled).nodes[0].role;
  }

  it("draws a status leaf as its own kind", () => {
    expect(roleOf({ kind: "status", status: "good", text_en: "ok" })).toBe("leaf-status");
  });

  it("draws an old quiet branch as no action even when it claims to be a recommendation", () => {
    expect(roleOf({ kind: "recommendation", action_type: "no_action", text_en: "ok" })).toBe(
      "leaf-noop",
    );
  });

  it("still draws alerts and recommendations as before", () => {
    expect(roleOf({ kind: "alert", action_type: "scout", severity: "warning", text_en: "x" })).toBe(
      "leaf-alert",
    );
    expect(roleOf({ kind: "recommendation", action_type: "scout", text_en: "x" })).toBe(
      "leaf-recommendation",
    );
  });
});
