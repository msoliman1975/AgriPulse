/**
 * The publish checks, named per node.
 *
 * Prompt 3 put the compiler on the backend, and PR #696 merged it as
 * `recommendations/folding_compiler.py`. This is the same rule set run in the
 * browser so the author sees a rejection while they are looking at the node
 * that caused it, rather than after a round trip.
 *
 * The two shapes are close but not identical, and the difference is the one
 * thing to get right when the endpoint is wired up (PR #703):
 *
 *   * its rule names are kebab-case (`register-without-code`), these are
 *     snake_case (`register_missing_code`);
 *   * it carries `node_ids`, a list, because one rejection can name several
 *     nodes; this carries a single `node_id`;
 *   * it already ships `message_en` and `message_ar`, so a wired panel should
 *     render the backend's own Arabic rather than translating from the rule.
 *
 * `RejectionRow` falls back to `detail` whenever it has no copy for a rule, so
 * an unmapped backend rejection still reads as a sentence rather than a key.
 *
 * Every rejection carries a `rule` the UI translates and a `detail` in English
 * for the cases where the backend knows something this copy does not. Nothing
 * here is a warning: a rejection blocks the publish.
 *
 * Rules, from docs/proposals/unified-decision-tree-engine.md sections 4 and 6.5:
 *
 *   switch_without_default   a switch that matches no case stops the walk
 *   register_not_declared    every register node's code must be in `registers`
 *   register_unknown_code    every `registers` entry must be in a catalogue
 *   register_missing_code    a register node with no code chosen
 *   unreached_stop           a path that never reaches `stop`
 *   dangling_pointer         a slot pointing at a node that is not there
 *   empty_slot               a slot left unfilled
 *   unreachable_node         a node the root cannot reach
 *   switch_case_no_target    a case with no `go`
 *   mixed_leaf_kinds         an old-style outcome leaf next to register nodes
 *   combination_unknown_code a rule naming a code the tree cannot register
 *   duplicate_combination    two rules matching the same finding set
 */

import {
  betaNodeKind,
  edgeKey,
  outgoingEdges,
  parseBetaDoc,
  readCombinations,
  readRegisters,
  reachableFrom,
  slotsOf,
  type BetaNode,
  type BetaTreeDoc,
  type EdgeSlot,
} from "./betaTree";
import { findingSetKey, isFindingSeverity } from "./betaConstants";

export type RejectionRule =
  | "yaml_unparsed"
  | "missing_root"
  | "unknown_root"
  | "switch_without_default"
  | "switch_default_unknown"
  | "switch_case_no_target"
  | "switch_no_cases"
  | "switch_no_subject"
  | "register_missing_code"
  | "register_bad_severity"
  | "register_not_declared"
  | "register_unknown_code"
  | "unreached_stop"
  | "dangling_pointer"
  | "empty_slot"
  | "unreachable_node"
  | "mixed_leaf_kinds"
  | "combination_unknown_code"
  | "combination_empty"
  | "duplicate_combination";

export interface CompileRejection {
  rule: RejectionRule;
  /** The node the author has to open. Null for a document-level rejection. */
  node_id: string | null;
  /** The edge to highlight, when the rejection is about one pointer. */
  edge_key?: string;
  /** Values the translated message interpolates. */
  params?: Record<string, string | number>;
  /** English fallback, for a rule this frontend has no copy for yet. */
  detail: string;
}

export interface CompileInput {
  yaml: string;
  /** Codes the finding catalogue resolves — platform first, then tenant. */
  knownFindingCodes: readonly string[];
}

export function compileBetaTree(input: CompileInput): CompileRejection[] {
  const doc = parseBetaDoc(input.yaml);
  if (!doc) {
    return [{ rule: "yaml_unparsed", node_id: null, detail: "The tree body is not valid YAML." }];
  }
  const out: CompileRejection[] = [];
  const nodes = doc.nodes ?? {};
  const known = new Set(input.knownFindingCodes);

  if (!doc.root) {
    out.push({ rule: "missing_root", node_id: null, detail: "The tree has no `root`." });
  } else if (!nodes[doc.root]) {
    out.push({
      rule: "unknown_root",
      node_id: doc.root,
      params: { node: doc.root },
      detail: `Root "${doc.root}" is not in \`nodes\`.`,
    });
  }

  const declared = readRegisters(doc);

  for (const [id, node] of Object.entries(nodes)) {
    const kind = betaNodeKind(node);

    // An old-style outcome leaf cannot sit in a tree that registers findings:
    // the fold reads the finding set, and the leaf would decide the card.
    if (node.outcome !== undefined) {
      out.push({
        rule: "mixed_leaf_kinds",
        node_id: id,
        params: { node: id },
        detail: `"${id}" carries an \`outcome\` block. A beta tree folds its findings; it has no outcome leaves.`,
      });
    }

    if (kind === "register") {
      const code = node.register?.code ?? "";
      if (!code) {
        out.push({
          rule: "register_missing_code",
          node_id: id,
          params: { node: id },
          detail: `"${id}" registers no finding — pick a code.`,
        });
      } else {
        if (!declared.includes(code)) {
          out.push({
            rule: "register_not_declared",
            node_id: id,
            params: { node: id, code },
            detail: `"${id}" registers "${code}", which is not in the tree's \`registers\` list.`,
          });
        }
        if (!known.has(code)) {
          out.push({
            rule: "register_unknown_code",
            node_id: id,
            params: { node: id, code },
            detail: `"${code}" is in no finding catalogue, platform or tenant.`,
          });
        }
      }
      const severity = node.register?.severity;
      if (!severity || !isFindingSeverity(severity)) {
        out.push({
          rule: "register_bad_severity",
          node_id: id,
          params: { node: id, severity: String(severity ?? "") },
          detail: `"${id}" has no valid severity.`,
        });
      }
    }

    if (kind === "switch") {
      const sw = node.switch ?? {};
      if (sw.on === undefined || sw.on === null) {
        out.push({
          rule: "switch_no_subject",
          node_id: id,
          params: { node: id },
          detail: `"${id}" switches on nothing — pick a reading.`,
        });
      }
      const cases = sw.cases ?? [];
      if (cases.length === 0) {
        out.push({
          rule: "switch_no_cases",
          node_id: id,
          params: { node: id },
          detail: `"${id}" has no cases. Every cell would take the default.`,
        });
      }
      cases.forEach((c, index) => {
        if (!c.go) {
          out.push({
            rule: "switch_case_no_target",
            node_id: id,
            edge_key: edgeKey(id, { kind: "case", index }),
            params: { node: id, position: index + 1 },
            detail: `Case ${index + 1} of "${id}" points nowhere.`,
          });
        }
      });
      // The one rule the designer must never let a save cross.
      if (!sw.default) {
        out.push({
          rule: "switch_without_default",
          node_id: id,
          edge_key: edgeKey(id, { kind: "default" }),
          params: { node: id },
          detail: `"${id}" has no default. A switch that matches no case stops the walk and the trace status is error.`,
        });
      } else if (!nodes[sw.default]) {
        out.push({
          rule: "switch_default_unknown",
          node_id: id,
          edge_key: edgeKey(id, { kind: "default" }),
          params: { node: id, target: sw.default },
          detail: `The default of "${id}" points at "${sw.default}", which is not a node.`,
        });
      }
    }

    // Empty and dangling pointers, for every kind that has one.
    for (const slot of slotsOf(node)) {
      if (kind === "switch") continue; // covered above, with better copy
      const target = readSlotTarget(node, slot);
      if (!target) {
        out.push({
          rule: "empty_slot",
          node_id: id,
          edge_key: edgeKey(id, slot),
          params: { node: id, slot: slot.kind },
          detail: `"${id}" has an empty \`${slot.kind}\` pointer.`,
        });
      } else if (!nodes[target]) {
        out.push({
          rule: "dangling_pointer",
          node_id: id,
          edge_key: edgeKey(id, slot),
          params: { node: id, slot: slot.kind, target },
          detail: `"${id}.${slot.kind}" points at "${target}", which is not a node.`,
        });
      }
    }
  }

  // Every entry of `registers` must resolve in a catalogue, whether or not a
  // node uses it — the fold reads the clause from the catalogue.
  for (const code of declared) {
    if (!known.has(code)) {
      out.push({
        rule: "register_unknown_code",
        node_id: null,
        params: { code },
        detail: `\`registers\` names "${code}", which is in no finding catalogue.`,
      });
    }
  }

  if (doc.root && nodes[doc.root]) {
    out.push(...reachabilityRejections(doc));
  }
  out.push(...combinationRejections(doc, declared));
  return out;
}

function readSlotTarget(node: BetaNode, slot: EdgeSlot): string | null {
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

/**
 * Two reachability answers in one walk.
 *
 * A node the root cannot reach is dead weight; a node from which no `stop` is
 * reachable is a walk that never folds, which is the check section 8 asks the
 * publish button to name.
 */
function reachabilityRejections(doc: BetaTreeDoc): CompileRejection[] {
  const nodes = doc.nodes ?? {};
  const out: CompileRejection[] = [];
  const reachable = reachableFrom(doc, doc.root!);

  for (const id of Object.keys(nodes)) {
    if (!reachable.has(id)) {
      out.push({
        rule: "unreachable_node",
        node_id: id,
        params: { node: id },
        detail: `"${id}" cannot be reached from the root.`,
      });
    }
  }

  // Can this node reach a stop? Memoised, with an in-progress marker so a
  // cycle resolves to "no" instead of recursing for ever.
  const answer = new Map<string, boolean>();
  const inProgress = new Set<string>();
  const reachesStop = (id: string): boolean => {
    const cached = answer.get(id);
    if (cached !== undefined) return cached;
    if (inProgress.has(id)) return false;
    const node = nodes[id];
    if (!node) return false;
    if (betaNodeKind(node) === "stop") {
      answer.set(id, true);
      return true;
    }
    inProgress.add(id);
    const ok = outgoingEdges(node).some((e) => reachesStop(e.to));
    inProgress.delete(id);
    answer.set(id, ok);
    return ok;
  };

  for (const id of reachable) {
    if (!nodes[id]) continue;
    if (!reachesStop(id)) {
      out.push({
        rule: "unreached_stop",
        node_id: id,
        params: { node: id },
        detail: `No route from "${id}" reaches a \`stop\` node.`,
      });
    }
  }
  return out;
}

function combinationRejections(doc: BetaTreeDoc, declared: string[]): CompileRejection[] {
  const out: CompileRejection[] = [];
  const rules = readCombinations(doc);
  const seen = new Map<string, number>();
  rules.forEach((rule, index) => {
    if (rule.codes.length === 0) {
      out.push({
        rule: "combination_empty",
        node_id: null,
        params: { position: index + 1 },
        detail: `Combination rule ${index + 1} names no findings.`,
      });
      return;
    }
    for (const code of rule.codes) {
      if (!declared.includes(code)) {
        out.push({
          rule: "combination_unknown_code",
          node_id: null,
          params: { position: index + 1, code },
          detail: `Combination rule ${index + 1} names "${code}", which this tree never registers.`,
        });
      }
    }
    const key = findingSetKey(rule.codes);
    const first = seen.get(key);
    if (first !== undefined) {
      out.push({
        rule: "duplicate_combination",
        node_id: null,
        params: { position: index + 1, first: first + 1, set: rule.codes.join(", ") },
        detail: `Combination rule ${index + 1} matches the same finding set as rule ${first + 1}.`,
      });
    } else {
      seen.set(key, index);
    }
  });
  return out;
}

/** Does anything block the publish? The button reads this, never a count of
 *  its own. */
export function blocksPublish(rejections: readonly CompileRejection[]): boolean {
  return rejections.length > 0;
}
