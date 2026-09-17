/**
 * Editing hints, named per node. Advisory only.
 *
 * The server's `folding_compiler` is the compiler. It runs on every save and
 * every publish and answers with a 422, and nothing here can let a version
 * through that it refused. This module exists for the gap in between: an
 * author dragging a switch about wants to be told the default is empty while
 * they are looking at the switch, not after a round trip.
 *
 * The two shapes are close but not identical, and the panel renders the
 * server's answer, not this one, whenever it has it:
 *
 *   * the server's rule names are kebab-case (`register-without-code`), these
 *     are snake_case (`register_missing_code`);
 *   * it carries `node_ids`, a list, because one rejection can name several
 *     nodes; this carries a single `node_id`;
 *   * it ships `message_en` and `message_ar`, so the panel renders the
 *     server's own Arabic rather than translating from the rule.
 *
 * `RejectionRow` falls back to `detail` whenever it has no copy for a rule, so
 * an unmapped server rejection still reads as a sentence rather than a key.
 *
 * So two rules hold, and the lockstep test enforces the first:
 *
 *   * every rule name here is a rule name the compiler emits. A hint that
 *     named a rule the server has never heard of would be this file
 *     inventing its own opinion, which is how two validators drift.
 *   * a hint never blocks the publish. The publish is held by the server's
 *     errors and by nothing else.
 *
 * The rules, from docs/proposals/unified-decision-tree-engine.md sections 4
 * and 6.5, under the compiler's own names:
 *
 *   switch-without-default    a switch that matches no case stops the walk
 *   register-not-declared     a register node's code must be in `registers`
 *   registers-unknown-code    every `registers` entry must be in a catalogue
 *   register-without-code     a register node with no code chosen
 *   path-without-stop         a path that never reaches `stop`
 *   unknown-target            a pointer naming a node that is not there,
 *                             or naming nothing at all
 *   unreachable-node          a node the root cannot reach
 *   switch-case-without-go    a case with no `go`
 *   mixed-shapes              an old-style outcome leaf beside register nodes
 *   combination-unknown-code  a rule naming a code the tree cannot register
 *   combination-duplicate-set two rules matching the same finding set
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

/**
 * The rule names this file may emit.
 *
 * Every one of them is a rule of `backend/app/modules/recommendations/
 * folding_compiler.py`. `betaCompile.lockstep.test.ts` reads that file and
 * fails when a name here is not one of its rules.
 */
export const HINT_RULES = [
  "not-a-mapping",
  "tree-bad-root",
  "switch-without-default",
  "switch-case-without-go",
  "switch-without-cases",
  "switch-without-on",
  "register-without-code",
  "register-bad-severity",
  "register-not-declared",
  "registers-unknown-code",
  "path-without-stop",
  "unknown-target",
  "unreachable-node",
  "mixed-shapes",
  "combination-unknown-code",
  "combination-without-codes",
  "combination-duplicate-set",
] as const;

export type HintRule = (typeof HINT_RULES)[number];

export interface EditorHint {
  /** The compiler's own name for this rule. One vocabulary, two sides —
   *  see `betaCompile.lockstep.test.ts`. */
  rule: HintRule;
  /**
   * Which copy to render.
   *
   * Not the same as `rule`, and deliberately so. Three different mistakes —
   * a pointer at a node that is gone, a pointer at nothing, a switch default
   * at a node that is gone — are all `unknown-target` to the compiler, and
   * telling an author "unknown target" when the truth is "you left the miss
   * branch empty" wastes the hint. The rule stays the server's word; this is
   * the sentence.
   */
  messageKey: string;
  /** The node the author has to open. Null for a document-level rejection. */
  node_id: string | null;
  /** The edge to highlight, when the rejection is about one pointer. */
  edge_key?: string;
  /** Values the translated message interpolates. */
  params?: Record<string, string | number>;
  /** English fallback, for a rule this frontend has no copy for yet. */
  detail: string;
}

export interface EditorHintInput {
  yaml: string;
  /** Codes the finding catalogue resolves — platform first, then tenant. */
  knownFindingCodes: readonly string[];
}

export function betaEditorHints(input: EditorHintInput): EditorHint[] {
  const doc = parseBetaDoc(input.yaml);
  if (!doc) {
    return [
      {
        rule: "not-a-mapping",
        messageKey: "yaml_unparsed",
        node_id: null,
        detail: "The tree body is not valid YAML.",
      },
    ];
  }
  const out: EditorHint[] = [];
  const nodes = doc.nodes ?? {};
  const known = new Set(input.knownFindingCodes);

  if (!doc.root) {
    out.push({
      rule: "tree-bad-root",
      messageKey: "missing_root",
      node_id: null,
      detail: "The tree has no `root`.",
    });
  } else if (!nodes[doc.root]) {
    out.push({
      rule: "tree-bad-root",
      messageKey: "unknown_root",
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
        rule: "mixed-shapes",
        messageKey: "mixed_leaf_kinds",
        node_id: id,
        params: { node: id },
        detail: `"${id}" carries an \`outcome\` block. A beta tree folds its findings; it has no outcome leaves.`,
      });
    }

    if (kind === "register") {
      const code = node.register?.code ?? "";
      if (!code) {
        out.push({
          rule: "register-without-code",
          messageKey: "register_missing_code",
          node_id: id,
          params: { node: id },
          detail: `"${id}" registers no finding — pick a code.`,
        });
      } else {
        if (!declared.includes(code)) {
          out.push({
            rule: "register-not-declared",
            messageKey: "register_not_declared",
            node_id: id,
            params: { node: id, code },
            detail: `"${id}" registers "${code}", which is not in the tree's \`registers\` list.`,
          });
        }
        if (!known.has(code)) {
          out.push({
            rule: "registers-unknown-code",
            messageKey: "register_unknown_code",
            node_id: id,
            params: { node: id, code },
            detail: `"${code}" is in no finding catalogue, platform or tenant.`,
          });
        }
      }
      const severity = node.register?.severity;
      if (!severity || !isFindingSeverity(severity)) {
        out.push({
          rule: "register-bad-severity",
          messageKey: "register_bad_severity",
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
          rule: "switch-without-on",
          messageKey: "switch_no_subject",
          node_id: id,
          params: { node: id },
          detail: `"${id}" switches on nothing — pick a reading.`,
        });
      }
      const cases = sw.cases ?? [];
      if (cases.length === 0) {
        out.push({
          rule: "switch-without-cases",
          messageKey: "switch_no_cases",
          node_id: id,
          params: { node: id },
          detail: `"${id}" has no cases. Every cell would take the default.`,
        });
      }
      cases.forEach((c, index) => {
        if (!c.go) {
          out.push({
            rule: "switch-case-without-go",
            messageKey: "switch_case_no_target",
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
          rule: "switch-without-default",
          messageKey: "switch_without_default",
          node_id: id,
          edge_key: edgeKey(id, { kind: "default" }),
          params: { node: id },
          detail: `"${id}" has no default. A switch that matches no case stops the walk and the trace status is error.`,
        });
      } else if (!nodes[sw.default]) {
        out.push({
          rule: "unknown-target",
          messageKey: "switch_default_unknown",
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
          rule: "unknown-target",
          messageKey: "empty_slot",
          node_id: id,
          edge_key: edgeKey(id, slot),
          params: { node: id, slot: slot.kind },
          detail: `"${id}" has an empty \`${slot.kind}\` pointer.`,
        });
      } else if (!nodes[target]) {
        out.push({
          rule: "unknown-target",
          messageKey: "dangling_pointer",
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
        rule: "registers-unknown-code",
        messageKey: "register_unknown_code",
        node_id: null,
        params: { code },
        detail: `\`registers\` names "${code}", which is in no finding catalogue.`,
      });
    }
  }

  if (doc.root && nodes[doc.root]) {
    out.push(...reachabilityHints(doc));
  }
  out.push(...combinationHints(doc, declared));
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
function reachabilityHints(doc: BetaTreeDoc): EditorHint[] {
  const nodes = doc.nodes ?? {};
  const out: EditorHint[] = [];
  const reachable = reachableFrom(doc, doc.root!);

  for (const id of Object.keys(nodes)) {
    if (!reachable.has(id)) {
      out.push({
        rule: "unreachable-node",
        messageKey: "unreachable_node",
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
        rule: "path-without-stop",
        messageKey: "unreached_stop",
        node_id: id,
        params: { node: id },
        detail: `No route from "${id}" reaches a \`stop\` node.`,
      });
    }
  }
  return out;
}

function combinationHints(doc: BetaTreeDoc, declared: string[]): EditorHint[] {
  const out: EditorHint[] = [];
  const rules = readCombinations(doc);
  const seen = new Map<string, number>();
  rules.forEach((rule, index) => {
    if (rule.codes.length === 0) {
      out.push({
        rule: "combination-without-codes",
        messageKey: "combination_empty",
        node_id: null,
        params: { position: index + 1 },
        detail: `Combination rule ${index + 1} names no findings.`,
      });
      return;
    }
    for (const code of rule.codes) {
      if (!declared.includes(code)) {
        out.push({
          rule: "combination-unknown-code",
          messageKey: "combination_unknown_code",
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
        rule: "combination-duplicate-set",
        messageKey: "duplicate_combination",
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

/**
 * Does anything need the author's attention before they try to publish?
 *
 * Deliberately NOT "does this block the publish". Nothing here blocks it:
 * the server decides, and a hint that was wrong would otherwise lock an
 * author out of a version the compiler would have accepted.
 */
export function hasEditorHints(hints: readonly EditorHint[]): boolean {
  return hints.length > 0;
}
