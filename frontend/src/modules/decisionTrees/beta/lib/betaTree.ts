/**
 * The beta tree document: five node kinds, a `registers` list and a
 * `combinations` table.
 *
 * Shape follows docs/proposals/unified-decision-tree-engine.md sections 4 and
 * 6.5. The engine discriminates a node by which key is present, exactly as the
 * current engine does, so this module reads the same way:
 *
 *   condition + on_match/on_miss   the existing two-way branch
 *   register  + next               record a finding and carry on
 *   set       + next               write a variable
 *   switch                         ordered cases, first match wins
 *   stop: true                     end the walk and fold
 *
 * Every helper is pure: it takes the YAML string, mutates a parsed copy and
 * returns a new string. The page holds the draft. That is the same contract as
 * `lib/treeStructure.ts`, which this file deliberately does not extend — the
 * existing editor must keep compiling against the two-way-only shape.
 */

import jsYaml from "js-yaml";

import {
  FINDING_SEVERITIES,
  type ActionType,
  type FindingSeverity,
  type FindingStatus,
} from "./betaConstants";

// ---- Document shape ---------------------------------------------------

export type BetaNodeKind = "condition" | "register" | "set" | "switch" | "stop";

export const BETA_NODE_KINDS: readonly BetaNodeKind[] = [
  "condition",
  "register",
  "set",
  "switch",
  "stop",
];

/** Comparison operators a switch case may use. `in` takes a list. */
export const SWITCH_OPS = ["ge", "gt", "le", "lt", "eq", "ne", "in"] as const;
export type SwitchOp = (typeof SWITCH_OPS)[number];

export interface SwitchCase {
  op: SwitchOp;
  value: number | string | boolean | (number | string)[];
  go: string;
}

export interface BetaNode {
  label_en?: string;
  label_ar?: string | null;

  // condition
  condition?: { tree?: unknown };
  on_match?: string | null;
  on_miss?: string | null;

  // register
  register?: { code?: string; severity?: FindingSeverity };

  // set
  set?: Record<string, unknown>;

  // switch
  switch?: {
    on?: unknown;
    cases?: SwitchCase[];
    default?: string;
  };

  // stop
  stop?: boolean;

  /** register and set continue to exactly one node. */
  next?: string | null;

  [k: string]: unknown;
}

export interface CombinationRule {
  /** The finding set this rule matches, exactly — not as a subset. */
  codes: string[];
  action_type: ActionType;
  status: FindingStatus;
  text_en: string;
  text_ar: string;
}

export interface BetaTreeDoc {
  code?: string;
  name_en?: string;
  name_ar?: string | null;
  description_en?: string | null;
  description_ar?: string | null;
  root?: string;
  nodes?: Record<string, BetaNode>;
  /** The codes this tree may register. The compiler checks every register
   *  node against it, and every entry against the finding catalogue. */
  registers?: string[];
  combinations?: CombinationRule[];
  [k: string]: unknown;
}

// ---- Parse / dump -----------------------------------------------------

export function parseBetaDoc(yaml: string): BetaTreeDoc | null {
  try {
    const doc = jsYaml.load(yaml);
    if (!doc || typeof doc !== "object" || Array.isArray(doc)) return null;
    return doc as BetaTreeDoc;
  } catch {
    return null;
  }
}

export function dumpBetaDoc(doc: BetaTreeDoc): string {
  return jsYaml.dump(doc, { sortKeys: false, lineWidth: 100, noRefs: true });
}

/** The kind of a node, read the way the engine reads it: by which key is
 *  present. A node carrying none of them is a condition with nothing filled
 *  in yet, which is what the author gets the moment they add one. */
export function betaNodeKind(node: BetaNode | undefined): BetaNodeKind {
  if (!node) return "condition";
  if (node.stop === true) return "stop";
  if (node.switch !== undefined) return "switch";
  if (node.register !== undefined) return "register";
  if (node.set !== undefined) return "set";
  return "condition";
}

/** Every node id this node points at, in reading order, with the label of
 *  the edge. Used by the layout, the reachability check and the compiler. */
export function outgoingEdges(
  node: BetaNode,
): Array<{ to: string; kind: "match" | "miss" | "next" | "case" | "default"; caseIndex?: number }> {
  const edges: Array<{
    to: string;
    kind: "match" | "miss" | "next" | "case" | "default";
    caseIndex?: number;
  }> = [];
  switch (betaNodeKind(node)) {
    case "condition":
      if (node.on_match) edges.push({ to: node.on_match, kind: "match" });
      if (node.on_miss) edges.push({ to: node.on_miss, kind: "miss" });
      break;
    case "register":
    case "set":
      if (node.next) edges.push({ to: node.next, kind: "next" });
      break;
    case "switch": {
      const cases = node.switch?.cases ?? [];
      cases.forEach((c, i) => {
        if (c.go) edges.push({ to: c.go, kind: "case", caseIndex: i });
      });
      if (node.switch?.default) edges.push({ to: node.switch.default, kind: "default" });
      break;
    }
    case "stop":
      break;
  }
  return edges;
}

/** Ids reachable from `fromId`, including it. Visits each node once so a
 *  cycle does not loop for ever. */
export function reachableFrom(doc: BetaTreeDoc, fromId: string): Set<string> {
  const nodes = doc.nodes ?? {};
  const seen = new Set<string>();
  const stack = [fromId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    const node = nodes[id];
    if (!node) continue;
    for (const edge of outgoingEdges(node)) stack.push(edge.to);
  }
  return seen;
}

/** Nodes that point at `targetId`. Named so a delete can say who still
 *  holds the pointer instead of silently orphaning it. */
export function referrersOf(doc: BetaTreeDoc, targetId: string): string[] {
  const out: string[] = [];
  for (const [id, node] of Object.entries(doc.nodes ?? {})) {
    if (outgoingEdges(node).some((e) => e.to === targetId)) out.push(id);
  }
  return out;
}

// ---- Node creation ----------------------------------------------------

const ID_PREFIX: Record<BetaNodeKind, string> = {
  condition: "cond",
  register: "reg",
  set: "set",
  switch: "sw",
  stop: "stop",
};

export function generateBetaNodeId(doc: BetaTreeDoc, kind: BetaNodeKind): string {
  const taken = new Set(Object.keys(doc.nodes ?? {}));
  for (let i = 1; i < 10_000; i++) {
    const candidate = `${ID_PREFIX[kind]}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  throw new Error(`generateBetaNodeId: ran out of candidates for kind=${kind}`);
}

export interface BuildNodeOptions {
  labelEn?: string;
  /**
   * The node a new switch should fall through to when no case matches.
   *
   * A switch with no default is rejected at publish, so the designer never
   * writes one without it. Section 4.3: "The default is required and the
   * compiler rejects a switch without one. The editor pre-fills it."
   */
  defaultGo?: string;
  /** What a register / set node continues to. */
  next?: string;
}

export function buildBetaNode(kind: BetaNodeKind, options: BuildNodeOptions = {}): BetaNode {
  switch (kind) {
    case "register":
      return {
        label_en: options.labelEn ?? "Record a finding",
        register: { code: "", severity: "warning" satisfies FindingSeverity },
        ...(options.next ? { next: options.next } : {}),
      };
    case "set":
      return {
        label_en: options.labelEn ?? "Set a variable",
        set: {},
        ...(options.next ? { next: options.next } : {}),
      };
    case "switch":
      return {
        label_en: options.labelEn ?? "Bands",
        switch: {
          on: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          cases: [],
          // Always written, even when the caller had nothing to suggest:
          // an absent default is the one thing publish refuses outright.
          default: options.defaultGo ?? "",
        },
      };
    case "stop":
      return { label_en: options.labelEn ?? "End", stop: true };
    case "condition":
    default:
      return {
        label_en: options.labelEn ?? "Decision",
        condition: {
          tree: {
            op: "lt",
            left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
            right: 0,
          },
        },
      };
  }
}

// ---- Structural edits -------------------------------------------------

export interface AttachArgs {
  parentId: string;
  /** Which outgoing slot of the parent to fill. */
  slot: EdgeSlot;
  kind: BetaNodeKind;
  newNodeId?: string;
  labelEn?: string;
}

/** One outgoing pointer, named the way the YAML names it. */
export type EdgeSlot =
  | { kind: "match" }
  | { kind: "miss" }
  | { kind: "next" }
  | { kind: "case"; index: number }
  | { kind: "default" };

function readSlot(node: BetaNode, slot: EdgeSlot): string | null {
  switch (slot.kind) {
    case "match":
      return node.on_match ?? null;
    case "miss":
      return node.on_miss ?? null;
    case "next":
      return node.next ?? null;
    case "case":
      return node.switch?.cases?.[slot.index]?.go ?? null;
    case "default":
      return node.switch?.default || null;
  }
}

function writeSlot(node: BetaNode, slot: EdgeSlot, target: string | null): void {
  switch (slot.kind) {
    case "match":
      if (target === null) delete node.on_match;
      else node.on_match = target;
      return;
    case "miss":
      if (target === null) delete node.on_miss;
      else node.on_miss = target;
      return;
    case "next":
      if (target === null) delete node.next;
      else node.next = target;
      return;
    case "case": {
      const c = node.switch?.cases?.[slot.index];
      if (c) c.go = target ?? "";
      return;
    }
    case "default":
      if (node.switch) node.switch.default = target ?? "";
      return;
  }
}

export interface AttachResult {
  yaml: string;
  newNodeId: string;
}

/**
 * Add a node and wire the parent's slot to it.
 *
 * When the new node is a switch its default is pre-filled with whatever the
 * slot pointed at before — the node the author was going to reach anyway. When
 * the slot was empty the default falls back to the parent's own continuation,
 * and when there is nothing to suggest it stays empty and the publish check
 * names it. It is written either way, never omitted.
 */
export function attachBetaNode(yaml: string, args: AttachArgs): AttachResult {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("attachBetaNode: source YAML did not parse");
  const nodes = (doc.nodes ??= {});
  const parent = nodes[args.parentId];
  if (!parent) throw new Error(`attachBetaNode: parent "${args.parentId}" not found`);

  const displaced = readSlot(parent, args.slot);
  const newId = args.newNodeId?.trim() || generateBetaNodeId(doc, args.kind);
  if (nodes[newId]) throw new Error(`attachBetaNode: node id "${newId}" already exists`);

  nodes[newId] = buildBetaNode(args.kind, {
    labelEn: args.labelEn,
    defaultGo: suggestSwitchDefault(doc, args.parentId, args.slot, displaced),
  });
  writeSlot(parent, args.slot, newId);
  return { yaml: dumpBetaDoc(doc), newNodeId: newId };
}

/**
 * What a new switch at this position should fall through to.
 *
 * In order: the node the slot already pointed at, then the parent's own
 * continuation, then the tree's single `stop` node when it has exactly one.
 * Returns "" when none of those exist; the author picks and the publish check
 * holds the publish until they do.
 */
export function suggestSwitchDefault(
  doc: BetaTreeDoc,
  parentId: string,
  slot: EdgeSlot,
  displaced: string | null,
): string {
  if (displaced) return displaced;
  const nodes = doc.nodes ?? {};
  const parent = nodes[parentId];
  if (parent) {
    const siblings = outgoingEdges(parent).filter((e) => {
      if (slot.kind === "case") return !(e.kind === "case" && e.caseIndex === slot.index);
      return e.kind !== slot.kind;
    });
    if (siblings.length > 0) return siblings[0].to;
  }
  return firstStopId(doc) ?? "";
}

/** The tree's `stop` node, in document order. Almost every beta tree has
 *  exactly one — every route ends at the same fold — so the first is the
 *  right fallback for anything that needs somewhere to go. */
export function firstStopId(doc: BetaTreeDoc): string | null {
  for (const [id, node] of Object.entries(doc.nodes ?? {})) {
    if (betaNodeKind(node) === "stop") return id;
  }
  return null;
}

/**
 * Give every switch a default, and never write an empty one.
 *
 * Section 4.3: the default is required and the compiler rejects a switch
 * without it. The editor already writes the key on every save, but it writes
 * `""` when the author has not picked a target, and `""` names no node — the
 * server refuses that exactly as it refuses a missing key.
 *
 * So this fills each empty default with the tree's `stop` node, and adds one
 * when the tree has none: falling through to the fold is the only answer that
 * is always correct, because a switch matching no case would otherwise end
 * the walk with the trace status `error`.
 *
 * Runs on the body about to be saved, not on every keystroke. An author who
 * has just added a switch and is on their way to its default should not have
 * the field filled in under their cursor.
 */
export function fillSwitchDefaults(yaml: string): string {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("fillSwitchDefaults: source YAML did not parse");
  const nodes = (doc.nodes ??= {});
  const empty = Object.entries(nodes).filter(
    ([, node]) => betaNodeKind(node) === "switch" && !node.switch?.default,
  );
  if (empty.length === 0) return yaml;

  let stopId = firstStopId(doc);
  if (!stopId) {
    stopId = generateBetaNodeId(doc, "stop");
    nodes[stopId] = buildBetaNode("stop");
  }
  for (const [, node] of empty) {
    if (node.switch) node.switch.default = stopId;
  }
  return dumpBetaDoc(doc);
}

/** Repoint one slot at an existing node. Refuses a self-loop and an unknown
 *  target; the rest of the restructure is the author's. */
export function rewireBetaSlot(
  yaml: string,
  parentId: string,
  slot: EdgeSlot,
  toNodeId: string,
): string {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("rewireBetaSlot: source YAML did not parse");
  const nodes = doc.nodes ?? {};
  const parent = nodes[parentId];
  if (!parent) throw new Error(`rewireBetaSlot: parent "${parentId}" not found`);
  if (!nodes[toNodeId]) throw new Error(`rewireBetaSlot: target "${toNodeId}" not found`);
  if (parentId === toNodeId) throw new Error("rewireBetaSlot: parent and target are the same node");
  writeSlot(parent, slot, toNodeId);
  return dumpBetaDoc(doc);
}

/** Replace a node's body wholesale. The details panel edits a node as a
 *  value and writes it back through here. */
export function setBetaNode(yaml: string, nodeId: string, node: BetaNode): string {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("setBetaNode: source YAML did not parse");
  const nodes = (doc.nodes ??= {});
  if (!nodes[nodeId]) throw new Error(`setBetaNode: node "${nodeId}" not found`);
  nodes[nodeId] = node;
  return dumpBetaDoc(doc);
}

export interface DeleteBetaResult {
  yaml: string;
  removed: string[];
}

/**
 * Delete a node and everything only it can reach.
 *
 * The walk is a graph, not a tree: a node inside the subtree may also be
 * reachable from outside it, and deleting that node would break the other
 * route. So the subtree is trimmed to the nodes no surviving node points at.
 */
export function deleteBetaNode(yaml: string, nodeId: string): DeleteBetaResult {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("deleteBetaNode: source YAML did not parse");
  if (doc.root === nodeId) throw new Error("deleteBetaNode: cannot delete the root node");
  const nodes = doc.nodes ?? {};
  if (!nodes[nodeId]) throw new Error(`deleteBetaNode: node "${nodeId}" not found`);

  // Clear every pointer aimed at the node, then drop whatever the root can
  // no longer reach. That removes the node's private subtree and keeps any
  // part of it a surviving route still needs.
  for (const node of Object.values(nodes)) {
    for (const slot of slotsOf(node)) {
      if (readSlot(node, slot) === nodeId) writeSlot(node, slot, null);
    }
  }
  delete nodes[nodeId];
  const reachable = doc.root ? reachableFrom(doc, doc.root) : new Set<string>();
  const removed = [nodeId];
  for (const id of Object.keys(nodes)) {
    if (!reachable.has(id)) {
      delete nodes[id];
      removed.push(id);
    }
  }
  return { yaml: dumpBetaDoc(doc), removed };
}

/** Every outgoing slot a node has, whether filled or not. */
export function slotsOf(node: BetaNode): EdgeSlot[] {
  switch (betaNodeKind(node)) {
    case "condition":
      return [{ kind: "match" }, { kind: "miss" }];
    case "register":
    case "set":
      return [{ kind: "next" }];
    case "switch":
      return [
        ...(node.switch?.cases ?? []).map((_, index) => ({ kind: "case" as const, index })),
        { kind: "default" as const },
      ];
    case "stop":
      return [];
  }
}

export function slotLabelKey(slot: EdgeSlot): string {
  return slot.kind === "case" ? `case` : slot.kind;
}

/** Stable identity for one edge, so the canvas can key and highlight it. */
export function edgeKey(fromId: string, slot: EdgeSlot): string {
  return slot.kind === "case" ? `${fromId}:case:${slot.index}` : `${fromId}:${slot.kind}`;
}

// ---- registers and combinations --------------------------------------

/** The declared `registers:` list, deduped and in document order. */
export function readRegisters(doc: BetaTreeDoc | null): string[] {
  if (!doc || !Array.isArray(doc.registers)) return [];
  return [...new Set(doc.registers.filter((c): c is string => typeof c === "string" && c !== ""))];
}

/** Codes actually registered by a `register` node, with the nodes that do it.
 *  The compiler needs the node ids to name the offender. */
export function registeredCodes(doc: BetaTreeDoc | null): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const [id, node] of Object.entries(doc?.nodes ?? {})) {
    if (betaNodeKind(node) !== "register") continue;
    const code = node.register?.code;
    if (!code) continue;
    out.set(code, [...(out.get(code) ?? []), id]);
  }
  return out;
}

export function writeRegisters(yaml: string, codes: string[]): string {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("writeRegisters: source YAML did not parse");
  doc.registers = [...new Set(codes)];
  return dumpBetaDoc(doc);
}

export function readCombinations(doc: BetaTreeDoc | null): CombinationRule[] {
  if (!doc || !Array.isArray(doc.combinations)) return [];
  return doc.combinations.filter((r): r is CombinationRule => Boolean(r) && Array.isArray(r.codes));
}

export function writeCombinations(yaml: string, rules: CombinationRule[]): string {
  const doc = parseBetaDoc(yaml);
  if (!doc) throw new Error("writeCombinations: source YAML did not parse");
  doc.combinations = rules.map((r) => ({ ...r, codes: [...new Set(r.codes)].sort() }));
  return dumpBetaDoc(doc);
}

// ---- Starter ----------------------------------------------------------

/** The smallest publishable beta tree: a condition, one register on the
 *  match side, and a single stop that both routes reach. */
export const STARTER_BETA_YAML = `code: REPLACE_ME
name_en: New beta tree
name_ar: شجرة تجريبية جديدة
description_en: One paragraph — what it checks and why.
description_ar: ""

registers:
  - dry

combinations: []

root: cond_1
nodes:
  cond_1:
    label_en: Is leaf water low?
    condition:
      tree:
        op: lt
        left: { source: indices, index_code: ndmi, key: baseline_deviation }
        right: -0.1
    on_match: reg_1
    on_miss: stop_1

  reg_1:
    label_en: Record low leaf water
    register:
      code: dry
      severity: warning
    next: stop_1

  stop_1:
    label_en: End
    stop: true
`;

/** The severities a register node may carry, exported so the picker and the
 *  validator read the same list. */
export const REGISTER_SEVERITIES = FINDING_SEVERITIES;
