/**
 * One folding walk, in one shape, from either source.
 *
 * Two places produce a walk and they pack it differently:
 *
 *   * **A dry run** answers `POST .../dry-run/cell` with steps that carry
 *     `kind` and `detail` as their own fields.
 *   * **A real run** stored its walk in `decision_tree_eval_traces.node_path`
 *     months ago. That column is free-form JSONB and had nowhere to put the
 *     two, so `service._folding_path_steps` packs them inside the step's
 *     values map, beside the values the condition read.
 *
 * Both normalise into `WalkStep` here, and the explainer never sees either
 * wire shape. Pure functions, no React, no network.
 *
 * **A folding walk is not shaped like an old-engine walk.** The old one ends
 * at a leaf and the leaf is the answer, which is what `lib/dryRunHighlight.ts`
 * assumes. A folding walk always ends at `stop`, and the answer is built from
 * `register` nodes spread along the route. So the highlight below has three
 * roles, not one: the nodes walked, the nodes that registered a finding, and
 * the end.
 */

import type { TreePathStepDTO } from "@/api/decisionTrees";

import { edgeKey, type EdgeSlot } from "./betaTree";

/** The node kinds a folding walk can visit. */
export type WalkStepKind = "condition" | "register" | "set" | "switch" | "stop";

const KINDS: readonly string[] = ["condition", "register", "set", "switch", "stop"];

/** One node the walk visited. */
export interface WalkStep {
  nodeId: string;
  kind: WalkStepKind | "unknown";
  /** The branch a condition took. Null on every other kind — nothing else
   *  has a yes or no answer. */
  matched: boolean | null;
  labelEn: string | null;
  labelAr: string | null;
  /** What a condition read, by reference name. Empty on every other kind. */
  values: Record<string, unknown>;
  /** What the node did: the finding a register wrote, the variables a set
   *  wrote, the case a switch chose. */
  detail: Record<string, unknown> | null;
}

/** One step of the dry run's `path`, as the server sends it. */
export interface DryRunWalkStep {
  node_id: string;
  kind: string;
  matched: boolean | null;
  label_en: string | null;
  label_ar: string | null;
  values: Record<string, unknown>;
  detail: Record<string, unknown> | null;
}

function asKind(raw: unknown): WalkStepKind | "unknown" {
  return typeof raw === "string" && KINDS.includes(raw) ? (raw as WalkStepKind) : "unknown";
}

/**
 * A list the caller may not have been sent.
 *
 * `Array.isArray` narrows a `readonly T[] | null | undefined` to `any[]`, not
 * to `readonly T[]`, so reading a field off an element afterwards is an unsafe
 * `any` access. The cast is what keeps the element type the signature already
 * promised.
 */
function asList<T>(raw: readonly T[] | null | undefined): readonly T[] {
  return Array.isArray(raw) ? (raw as readonly T[]) : [];
}

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null;
}

/** The dry run's own shape. Every field is already where it belongs. */
export function walkStepsFromDryRun(
  path: readonly DryRunWalkStep[] | null | undefined,
): WalkStep[] {
  return asList(path).map((step) => ({
    nodeId: step.node_id,
    kind: asKind(step.kind),
    matched: typeof step.matched === "boolean" ? step.matched : null,
    labelEn: step.label_en ?? null,
    labelAr: step.label_ar ?? null,
    values: asRecord(step.values) ?? {},
    detail: asRecord(step.detail),
  }));
}

/**
 * Whether a stored trace came from the folding engine.
 *
 * Read off the walk, not off the tree. `service._folding_path_steps` writes a
 * `kind` into every step's values map and the old engine writes none, so one
 * step with a kind is the whole test. Asking the tree instead would mean a
 * second read before a screen could decide what to draw.
 */
export function isFoldingPath(path: readonly TreePathStepDTO[] | null | undefined): boolean {
  return asList(path).some(
    (step) => typeof (step.values as { kind?: unknown } | undefined)?.kind === "string",
  );
}

/**
 * A stored trace row's `node_path`.
 *
 * `kind` and `detail` are lifted back out of the values map, and what is left
 * is what the condition read. A row written by the old engine has no `kind`
 * at all; it comes back as `unknown` rather than being dropped, because a
 * step the explainer cannot name is still a step the walk took.
 */
export function walkStepsFromTrace(
  path: readonly TreePathStepDTO[] | null | undefined,
): WalkStep[] {
  return asList(path).map((step) => {
    const packed = asRecord(step.values) ?? {};
    const { kind, detail, ...values } = packed;
    return {
      nodeId: step.node_id,
      kind: asKind(kind),
      matched: typeof step.matched === "boolean" ? step.matched : null,
      labelEn: step.label_en ?? null,
      labelAr: step.label_ar ?? null,
      values,
      detail: asRecord(detail),
    };
  });
}

/** What the canvas draws for one walk. */
export interface WalkHighlight {
  /** Every node on the route. */
  nodes: Set<string>;
  /** Every edge the walk traversed, keyed the way `BetaCanvas` keys them. */
  edges: Set<string>;
  /** Nodes that wrote a finding. Marked apart from the rest of the route,
   *  because they are what the card is made of. */
  registerNodes: Set<string>;
  /** Where the walk ended. Null when it never reached a stop node. */
  stopNodeId: string | null;
  /** The last node reached when the walk failed, else null. A walk that
   *  errored ends on the node that could not be resolved, and that node is
   *  the whole answer to "where did this fall over". */
  errorNodeId: string | null;
}

/**
 * Which outgoing slot this step took.
 *
 * Read off the step itself, never off the tree. A condition says so with
 * `matched`; a switch names the case it chose in `detail.case`, with null
 * meaning the default. Matching the next step's node id against the node's
 * slots would be the other way to do it, and it answers wrongly whenever two
 * slots point at the same node.
 */
function slotTaken(step: WalkStep): EdgeSlot | null {
  switch (step.kind) {
    case "condition":
      if (step.matched === null) return null;
      return step.matched ? { kind: "match" } : { kind: "miss" };
    case "register":
    case "set":
      return { kind: "next" };
    case "switch": {
      const chosen = step.detail?.case;
      if (chosen === null || chosen === undefined) return { kind: "default" };
      return typeof chosen === "number" ? { kind: "case", index: chosen } : null;
    }
    default:
      return null;
  }
}

/**
 * The sets the canvas needs, from one walk.
 *
 * The last step's edge is never counted. A walk ends either at `stop`, which
 * has no outgoing slot, or on a failure, where the pointer it was about to
 * follow is exactly the thing that did not work.
 */
export function walkHighlight(steps: readonly WalkStep[]): WalkHighlight {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  const registerNodes = new Set<string>();
  let stopNodeId: string | null = null;

  steps.forEach((step, index) => {
    nodes.add(step.nodeId);
    if (step.kind === "register") registerNodes.add(step.nodeId);
    if (step.kind === "stop") stopNodeId = step.nodeId;
    if (index === steps.length - 1) return;
    const slot = slotTaken(step);
    if (slot !== null) edges.add(edgeKey(step.nodeId, slot));
  });

  const last = steps.length > 0 ? steps[steps.length - 1] : null;
  return {
    nodes,
    edges,
    registerNodes,
    stopNodeId,
    errorNodeId: stopNodeId === null && last !== null ? last.nodeId : null,
  };
}

/**
 * What a register step wrote, for the step list's header.
 *
 * `raised` is the part worth showing: the same code registered twice keeps
 * one entry, and the second register only counts when it raised the
 * severity. A reader who sees the code twice and no note would think the
 * walk double-counted it.
 */
export interface RegisteredDetail {
  code: string;
  severity: string | null;
  repeat: boolean;
  raised: boolean;
}

export function registeredDetail(step: WalkStep): RegisteredDetail | null {
  const code = step.detail?.code;
  if (step.kind !== "register" || typeof code !== "string") return null;
  const severity = step.detail?.severity;
  return {
    code,
    severity: typeof severity === "string" ? severity : null,
    repeat: step.detail?.repeat === true,
    raised: step.detail?.raised === true,
  };
}

/** The variable names a `set` step wrote, in the order it wrote them. */
export function writtenNames(step: WalkStep): string[] {
  const wrote = asRecord(step.detail?.wrote);
  return wrote === null ? [] : Object.keys(wrote);
}

/** The values a `set` step wrote. */
export function writtenValues(step: WalkStep): Record<string, unknown> {
  return asRecord(step.detail?.wrote) ?? {};
}

/**
 * A resolved value as one short string.
 *
 * Numbers keep three decimals at most: an index mean arrives as
 * 0.3142857142857143 and no agronomist reads past the third digit. Absent is
 * its own word rather than an empty cell, because "the tree could not read
 * this" is why a condition went the way it did.
 */
export function formatValue(value: unknown, absent: string): string {
  if (value === null || value === undefined) return absent;
  if (typeof value === "string") return value;
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
  }
  if (typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return (value as unknown[]).map((v) => formatValue(v, absent)).join(", ");
  }
  // Everything left is an object, or something with no useful text of its own
  // (a symbol, a function). `String()` on either gives "[object Object]", so
  // JSON is the only honest answer, and `undefined` back from it means there
  // was nothing to say.
  return JSON.stringify(value) ?? absent;
}
