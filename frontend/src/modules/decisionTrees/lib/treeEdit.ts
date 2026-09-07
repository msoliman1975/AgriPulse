// Pure-fn helpers for applying visual edits to a tree's YAML source (PR-D2).
//
// The viewer page holds a `NodeEditBuffer` of patches keyed by node id;
// `applyEditsToYaml` parses the original YAML, applies the patches, and
// dumps a new YAML string ready to send to POST
// /decision-trees/{code}/versions as a new draft.
//
// Why patch the parsed YAML rather than emit YAML from the compiled
// JSON: the compiled JSON normalizes shape (e.g. drops original key
// order, strips comments). Patching the parsed YAML preserves
// everything the author wrote that we didn't touch — labels, comments
// on unedited nodes, key ordering at the top level — at the small
// cost that js-yaml's dump will re-emit edited regions in its own
// canonical style. For V1 that's acceptable; later we could swap to
// a comment-preserving YAML library if it matters.

import jsYaml from "js-yaml";

/** The four things a terminal node can be.
 *
 * `status` says what the block is without asking anyone to do anything;
 * `no_action` says the tree ran and has nothing to say. Before those two
 * existed, every quiet branch wrote `action_type: no_action` and no row at
 * all, so "checked and fine" and "never ran" looked the same on screen.
 */
export type LeafKind = "alert" | "recommendation" | "status" | "no_action";

export interface LeafOutcomePatch {
  action_type?: string;
  kind?: LeafKind;
  /** One of the five platform status codes. Only a `status` leaf names one. */
  status?: string;
  severity?: string;
  // confidence is sent as a number; YAML dump prints it natively.
  confidence?: number;
  text_en?: string;
  text_ar?: string | null;
  valid_for_hours?: number | null;
}

export interface NodePatch {
  label_en?: string;
  label_ar?: string | null;
  outcome?: LeafOutcomePatch;
}

export type NodeEditBuffer = Record<string, NodePatch>;

/** Returns true when ``buffer`` has at least one non-empty patch. */
export function hasEdits(buffer: NodeEditBuffer): boolean {
  return Object.values(buffer).some((patch) => Object.keys(patch).length > 0);
}

/** Merge a partial patch into the existing buffer entry for ``nodeId``. */
export function patchBuffer(
  buffer: NodeEditBuffer,
  nodeId: string,
  patch: NodePatch,
): NodeEditBuffer {
  const prior = buffer[nodeId] ?? {};
  const merged: NodePatch = { ...prior, ...patch };
  if (patch.outcome) {
    merged.outcome = { ...(prior.outcome ?? {}), ...patch.outcome };
  }
  return { ...buffer, [nodeId]: merged };
}

interface ParsedYamlDoc {
  nodes?: Record<string, ParsedYamlNode>;
  [k: string]: unknown;
}

interface ParsedYamlNode {
  outcome?: Record<string, unknown>;
  label_en?: string;
  label_ar?: string | null;
  [k: string]: unknown;
}

/** Apply every patch in ``buffer`` to ``yaml`` and dump the result.
 *
 * Patches that name a node id not present in the YAML are silently
 * skipped — the visual layer should never produce such patches, but
 * defending here avoids losing other valid edits if a stale node
 * sneaks through.
 *
 * Leaf-kind transitions clear the fields that are no longer meaningful,
 * so the persisted YAML stays coherent with what compile_tree validates:
 * ``alert`` drops ``confidence``, ``recommendation`` drops ``severity``,
 * ``status`` drops all three of ``action_type`` / ``severity`` /
 * ``confidence`` and gains a status code, and ``no_action`` drops
 * everything but its own ``action_type: no_action``.
 *
 * The status drop matters more than the others: the loader REFUSES a
 * ``status`` on any leaf that is not a status leaf, because an alert that
 * declared `good` would paint itself green while opening a red card.
 */
export function applyEditsToYaml(
  yaml: string,
  buffer: NodeEditBuffer,
): string {
  const doc = jsYaml.load(yaml) as ParsedYamlDoc;
  const nodes = doc?.nodes;
  if (!nodes || typeof nodes !== "object") {
    return yaml;
  }
  for (const [nodeId, patch] of Object.entries(buffer)) {
    const node = nodes[nodeId];
    if (!node || Object.keys(patch).length === 0) continue;
    if (patch.label_en !== undefined) node.label_en = patch.label_en;
    if (patch.label_ar !== undefined) node.label_ar = patch.label_ar;
    if (patch.outcome) {
      const outcome = node.outcome ?? {};
      Object.assign(outcome, patch.outcome);
      // Kind transition cleanup: drop the field that doesn't apply
      // to the new kind so the loader's validation passes.
      const newKind = patch.outcome.kind ?? outcome.kind;
      if (newKind === "alert" && patch.outcome.confidence === undefined) {
        delete outcome.confidence;
      }
      if (newKind === "recommendation" && patch.outcome.severity === undefined) {
        delete outcome.severity;
      }
      if (newKind === "status") {
        // A status leaf asks for no work, so it types no action and ranks
        // itself by its status code rather than by a severity.
        delete outcome.action_type;
        delete outcome.severity;
        delete outcome.confidence;
        if (outcome.status === undefined) outcome.status = "good";
      }
      if (newKind === "no_action") {
        delete outcome.status;
        delete outcome.severity;
        delete outcome.confidence;
        // The spelling every tree published before the four kinds existed
        // uses, and the one the loader reads as kind=no_action.
        outcome.action_type = "no_action";
      }
      if (newKind !== "status" && patch.outcome.status === undefined) {
        delete outcome.status;
      }
      node.outcome = outcome;
    }
  }
  // sortKeys: false preserves key order from the parsed doc. lineWidth
  // wide enough to keep one-line scalars on one line for readability.
  return jsYaml.dump(doc, { sortKeys: false, lineWidth: 100, noRefs: true });
}
