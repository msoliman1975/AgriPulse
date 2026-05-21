// Structural edits to a tree's YAML source (PR-D4).
//
// Property edits (labels, outcome fields) live in `treeEdit.ts` and
// apply to YAML at save time. Structural edits — add child, delete
// subtree, change kind — must apply eagerly so the canvas reflects
// the new shape immediately. We mutate the parsed YAML doc, dump
// it back to a string, and return that as the new "draft YAML".
//
// All helpers are pure. None of them call into React state — the
// caller (viewer page) holds the draft YAML in state and passes it
// in / receives the new string back.

import jsYaml from "js-yaml";

export type NodeKind =
  | "decision"
  | "leaf-recommendation"
  | "leaf-alert"
  | "leaf-noop";

export type Branch = "match" | "miss";

/** Shape of a node as it appears in the YAML doc. Loose because YAML
 *  authors can sprinkle extra fields and we want round-trip to preserve
 *  them. */
export interface YamlNode {
  condition?: { tree?: unknown };
  on_match?: string | null;
  on_miss?: string | null;
  outcome?: {
    action_type?: string;
    kind?: string;
    severity?: string;
    confidence?: number | string;
    text_en?: string;
    text_ar?: string | null;
    valid_for_hours?: number | null;
    parameters?: Record<string, unknown>;
  };
  label_en?: string;
  label_ar?: string | null;
  [k: string]: unknown;
}

export interface YamlDoc {
  root?: string;
  nodes?: Record<string, YamlNode>;
  [k: string]: unknown;
}

// ---- Starter ----------------------------------------------------------

/** YAML for the "start from scratch" tree. Includes a root decision
 *  pre-wired to two placeholder no-op leaves so the backend's
 *  compile_tree validator passes on create. Once the tree exists,
 *  the author deletes the placeholders from the canvas and adds the
 *  real structure.
 *
 *  Why not start with empty branches: backend rejects a decision
 *  node without `on_match` / `on_miss` at compile time, so create
 *  would 422. Two placeholder leaves are the smallest valid tree. */
export const STARTER_TREE_YAML = `code: REPLACE_ME
name_en: New tree
name_ar: شجرة جديدة
description_en: One-paragraph what + why.
description_ar: ""

crop_code: null
applicable_regions: []

root: root
nodes:
  root:
    label_en: Root decision
    condition:
      tree:
        op: lt
        left: { source: indices, index_code: ndvi, key: baseline_deviation }
        right: 0
    on_match: placeholder_match
    on_miss: placeholder_miss

  placeholder_match:
    label_en: Replace me
    outcome:
      action_type: no_action
      kind: recommendation
      confidence: 0.5
      text_en: Replace this leaf with a real action.
      text_ar: ""

  placeholder_miss:
    label_en: Replace me
    outcome:
      action_type: no_action
      kind: recommendation
      confidence: 0.5
      text_en: Replace this leaf with a real action.
      text_ar: ""
`;

// ---- Read helpers -----------------------------------------------------

/** Parse YAML to a doc. Returns null if it can't parse or the result
 *  isn't an object — caller should fall back to the prior draft. */
export function parseYamlDoc(yaml: string): YamlDoc | null {
  try {
    const doc = jsYaml.load(yaml);
    if (!doc || typeof doc !== "object") return null;
    return doc as YamlDoc;
  } catch {
    return null;
  }
}

function dumpYaml(doc: YamlDoc): string {
  return jsYaml.dump(doc, { sortKeys: false, lineWidth: 100, noRefs: true });
}

/** Returns the ids of all nodes that point at `targetId` via
 *  on_match or on_miss. Used to refuse a delete that would orphan a
 *  pointer somewhere else in the tree. */
export function findReferrers(doc: YamlDoc, targetId: string): string[] {
  const referrers: string[] = [];
  const nodes = doc.nodes ?? {};
  for (const [id, node] of Object.entries(nodes)) {
    if (node.on_match === targetId || node.on_miss === targetId) {
      referrers.push(id);
    }
  }
  return referrers;
}

/** Compute the full set of descendant ids reachable from `rootId`
 *  via on_match / on_miss pointers, including `rootId` itself. Visits
 *  each node at most once so cycles don't loop forever. */
export function collectSubtree(doc: YamlDoc, rootId: string): Set<string> {
  const nodes = doc.nodes ?? {};
  const visited = new Set<string>();
  const stack = [rootId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    const node = nodes[id];
    if (!node) continue;
    if (node.on_match) stack.push(node.on_match);
    if (node.on_miss) stack.push(node.on_miss);
  }
  return visited;
}

// ---- Structural ops ---------------------------------------------------

/** Generate a node id that doesn't collide with anything in the doc.
 *  Format: `${kindPrefix}_${counter}`. Counter walks up from 1 so the
 *  YAML stays human-readable. */
export function generateNodeId(doc: YamlDoc, kind: NodeKind): string {
  const prefix =
    kind === "decision"
      ? "decision"
      : kind === "leaf-recommendation"
        ? "leaf_rec"
        : kind === "leaf-alert"
          ? "leaf_alert"
          : "leaf_noop";
  const taken = new Set(Object.keys(doc.nodes ?? {}));
  for (let i = 1; i < 10_000; i++) {
    const candidate = `${prefix}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  // Pathological fallback — exhaustion is so unlikely we treat it as
  // a developer-visible signal rather than silently overwriting.
  throw new Error(`generateNodeId: ran out of candidates for kind=${kind}`);
}

/** Build a fresh node body of the requested kind. Outcomes get sensible
 *  defaults so the new node is structurally valid (compiles), even
 *  though the author still needs to fill in meaningful text/thresholds. */
export function buildNodeBody(kind: NodeKind, labelEn?: string): YamlNode {
  if (kind === "decision") {
    return {
      label_en: labelEn ?? "Decision",
      condition: {
        tree: {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: 0,
        },
      },
      // on_match / on_miss left absent — canvas will surface a `+`
      // port for the author to attach children. The structural
      // validator (`validateTreeStructure`) treats absent pointers as
      // an error so save stays gated until both are filled.
    };
  }
  if (kind === "leaf-alert") {
    return {
      label_en: labelEn ?? "Alert",
      outcome: {
        action_type: "scout",
        kind: "alert",
        severity: "warning",
        text_en: "Investigate.",
        text_ar: null,
      },
    };
  }
  if (kind === "leaf-recommendation") {
    return {
      label_en: labelEn ?? "Recommendation",
      outcome: {
        action_type: "scout",
        kind: "recommendation",
        confidence: 0.7,
        text_en: "Suggested action.",
        text_ar: null,
      },
    };
  }
  return {
    label_en: labelEn ?? "No action",
    outcome: {
      action_type: "no_action",
      kind: "recommendation",
      confidence: 0.9,
      text_en: "No action.",
      text_ar: null,
    },
  };
}

export interface AddNodeArgs {
  parentId: string;
  branch: Branch;
  kind: NodeKind;
  /** Optional explicit id — falls back to `generateNodeId`. */
  newNodeId?: string;
  /** Optional label_en to seed onto the new node. */
  labelEn?: string;
}

export interface AddNodeResult {
  yaml: string;
  newNodeId: string;
}

/** Add a child node under a parent's branch pointer and wire the
 *  parent's `on_match` / `on_miss` to point at it. Returns the new
 *  YAML plus the id that was used. Refuses if the parent doesn't
 *  exist, the parent isn't a decision (leaves can't have children),
 *  or the requested branch already points somewhere — the author
 *  should delete the existing subtree first. */
export function applyAddNode(yaml: string, args: AddNodeArgs): AddNodeResult {
  const doc = parseYamlDoc(yaml);
  if (!doc) throw new Error("applyAddNode: source YAML did not parse");
  const nodes = (doc.nodes ??= {});
  const parent = nodes[args.parentId];
  if (!parent) {
    throw new Error(`applyAddNode: parent "${args.parentId}" not found`);
  }
  if (parent.outcome) {
    throw new Error(
      `applyAddNode: parent "${args.parentId}" is a leaf; cannot add children`,
    );
  }
  const branchKey = args.branch === "match" ? "on_match" : "on_miss";
  if (parent[branchKey]) {
    throw new Error(
      `applyAddNode: branch ${branchKey} on "${args.parentId}" already filled`,
    );
  }
  const newId = args.newNodeId?.trim() || generateNodeId(doc, args.kind);
  if (nodes[newId]) {
    throw new Error(`applyAddNode: node id "${newId}" already exists`);
  }
  nodes[newId] = buildNodeBody(args.kind, args.labelEn);
  parent[branchKey] = newId;
  return { yaml: dumpYaml(doc), newNodeId: newId };
}

export interface DeleteNodeOptions {
  /** When true, removes the node and every descendant reachable from
   *  it. When false (default), only removes the single node — useful
   *  if the caller wants to re-attach the children manually first. */
  cascade?: boolean;
}

export interface DeleteNodeResult {
  yaml: string;
  /** Ids that were removed. Always includes the requested id; extra
   *  entries are the descendants when `cascade` is true. */
  removed: string[];
}

/** Delete a node from the tree. Clears the parent's branch pointer
 *  that referenced it. Refuses to delete the root. Refuses if a
 *  node outside the deleted subtree still points at the target —
 *  the author needs to reroute that pointer first. */
export function applyDeleteNode(
  yaml: string,
  nodeId: string,
  options: DeleteNodeOptions = {},
): DeleteNodeResult {
  const cascade = options.cascade ?? true;
  const doc = parseYamlDoc(yaml);
  if (!doc) throw new Error("applyDeleteNode: source YAML did not parse");
  if (doc.root === nodeId) {
    throw new Error("applyDeleteNode: cannot delete the root node");
  }
  const nodes = doc.nodes ?? {};
  if (!nodes[nodeId]) {
    throw new Error(`applyDeleteNode: node "${nodeId}" not found`);
  }
  const subtree = cascade ? collectSubtree(doc, nodeId) : new Set([nodeId]);
  // Refuse if any *external* node still points at something inside
  // the about-to-be-removed subtree (other than the parent of the
  // root of the subtree, which we'll clear below).
  for (const [id, node] of Object.entries(nodes)) {
    if (subtree.has(id)) continue;
    for (const branch of ["on_match", "on_miss"] as const) {
      const target = node[branch];
      if (target && subtree.has(target) && target !== nodeId) {
        throw new Error(
          `applyDeleteNode: cannot delete — "${id}.${branch}" still points at "${target}" inside the subtree`,
        );
      }
    }
  }
  // Clear the parent pointer that aimed at `nodeId`.
  for (const node of Object.values(nodes)) {
    if (node.on_match === nodeId) node.on_match = null;
    if (node.on_miss === nodeId) node.on_miss = null;
  }
  // Remove every node in the subtree.
  for (const id of subtree) {
    delete nodes[id];
  }
  // js-yaml emits `null` for null values, but the schema expects the
  // key to be absent rather than null. Strip null pointers so the
  // serialized YAML matches the on-disk style.
  for (const node of Object.values(nodes)) {
    if (node.on_match === null) delete node.on_match;
    if (node.on_miss === null) delete node.on_miss;
  }
  return { yaml: dumpYaml(doc), removed: [...subtree] };
}

export interface RewireBranchArgs {
  parentId: string;
  branch: Branch;
  /** Target node to point the branch at. Must already exist. */
  toNodeId: string;
}

/** Repoint a decision node's `on_match` or `on_miss` at a different
 *  existing node. Refuses if either node is missing, if `parentId` is
 *  a leaf, or if the target equals the parent (self-loop). Doesn't
 *  delete the previous target — orphans are the author's to clean up
 *  from the canvas, since the rewire might be one step in a larger
 *  restructuring. */
export function applyRewireBranch(yaml: string, args: RewireBranchArgs): string {
  const doc = parseYamlDoc(yaml);
  if (!doc) throw new Error("applyRewireBranch: source YAML did not parse");
  const nodes = doc.nodes ?? {};
  const parent = nodes[args.parentId];
  if (!parent) {
    throw new Error(`applyRewireBranch: parent "${args.parentId}" not found`);
  }
  if (parent.outcome) {
    throw new Error(
      `applyRewireBranch: parent "${args.parentId}" is a leaf; cannot wire children`,
    );
  }
  if (!nodes[args.toNodeId]) {
    throw new Error(`applyRewireBranch: target "${args.toNodeId}" not found`);
  }
  if (args.parentId === args.toNodeId) {
    throw new Error("applyRewireBranch: parent and target are the same node");
  }
  const branchKey = args.branch === "match" ? "on_match" : "on_miss";
  parent[branchKey] = args.toNodeId;
  return dumpYaml(doc);
}

/** Replace a decision node's `condition.tree` with `newTree`. Pure —
 *  returns the new YAML string. Refuses if the target node doesn't
 *  exist or is a leaf (leaves have no condition). When `newTree` is
 *  undefined the condition block is cleared entirely (use cautiously —
 *  the loader requires every decision to have a condition). */
export function applySetNodeCondition(
  yaml: string,
  nodeId: string,
  newTree: unknown,
): string {
  const doc = parseYamlDoc(yaml);
  if (!doc) throw new Error("applySetNodeCondition: source YAML did not parse");
  const nodes = doc.nodes ?? {};
  const node = nodes[nodeId];
  if (!node) {
    throw new Error(`applySetNodeCondition: node "${nodeId}" not found`);
  }
  if (node.outcome) {
    throw new Error(
      `applySetNodeCondition: node "${nodeId}" is a leaf; leaves have no condition`,
    );
  }
  if (newTree === undefined) {
    delete node.condition;
  } else {
    node.condition = { tree: newTree };
  }
  return dumpYaml(doc);
}

/** Return the ids of nodes that exist in `nodes:` but aren't reachable
 *  from the root via on_match / on_miss pointers. Orphans typically
 *  come from rewires that abandoned a subtree — the canvas walks from
 *  root so they vanish visually, but they sit in the YAML until the
 *  author cleans them up. Returns the ids in stable order. */
export function findUnreachableNodes(yaml: string): string[] {
  const doc = parseYamlDoc(yaml);
  if (!doc || !doc.root || !doc.nodes) return [];
  const reachable = collectSubtree(doc, doc.root);
  return Object.keys(doc.nodes)
    .filter((id) => !reachable.has(id))
    .sort();
}

/** Remove every node not reachable from root. Pure — returns the new
 *  YAML. Used by the canvas "Clean up unreachable" button. */
export function applyDeleteUnreachable(yaml: string): string {
  const doc = parseYamlDoc(yaml);
  if (!doc || !doc.root || !doc.nodes) return yaml;
  const reachable = collectSubtree(doc, doc.root);
  const nodes = doc.nodes;
  for (const id of Object.keys(nodes)) {
    if (!reachable.has(id)) {
      delete nodes[id];
    }
  }
  return dumpYaml(doc);
}

// ---- Validation -------------------------------------------------------

export interface StructuralError {
  /** Optional node id the error refers to. Null = doc-level error. */
  nodeId: string | null;
  message: string;
}

/** Check the YAML for structural problems that would make it fail
 *  backend compilation. Used to gate the Save button so the author
 *  sees the error before the round-trip. Does NOT validate semantic
 *  things (signal codes exist, expressions are well-typed, etc.) —
 *  the backend compile is authoritative for that. */
export function validateTreeStructure(yaml: string): StructuralError[] {
  const errors: StructuralError[] = [];
  const doc = parseYamlDoc(yaml);
  if (!doc) {
    errors.push({ nodeId: null, message: "YAML did not parse." });
    return errors;
  }
  const nodes = doc.nodes ?? {};
  const ids = Object.keys(nodes);
  if (!doc.root) {
    errors.push({ nodeId: null, message: "Missing `root` pointer." });
  } else if (!nodes[doc.root]) {
    errors.push({
      nodeId: doc.root,
      message: `Root "${doc.root}" not present in nodes.`,
    });
  }
  for (const id of ids) {
    const node = nodes[id];
    const isDecision = !node.outcome;
    if (isDecision) {
      if (!node.on_match) {
        errors.push({
          nodeId: id,
          message: "Decision is missing `on_match` child.",
        });
      } else if (!nodes[node.on_match]) {
        errors.push({
          nodeId: id,
          message: `\`on_match\` points at unknown node "${node.on_match}".`,
        });
      }
      if (!node.on_miss) {
        errors.push({
          nodeId: id,
          message: "Decision is missing `on_miss` child.",
        });
      } else if (!nodes[node.on_miss]) {
        errors.push({
          nodeId: id,
          message: `\`on_miss\` points at unknown node "${node.on_miss}".`,
        });
      }
    } else {
      // Leaf: cleanup-time invariant — outcome must have action_type.
      if (!node.outcome?.action_type) {
        errors.push({
          nodeId: id,
          message: "Leaf outcome is missing `action_type`.",
        });
      }
    }
  }
  return errors;
}
