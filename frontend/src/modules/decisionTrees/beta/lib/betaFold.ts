/**
 * The fold, run in the browser.
 *
 * Section 5: at `stop` the engine holds a set of findings and produces one
 * card. A combination rule matching the set EXACTLY supplies the text; with no
 * matching rule the text is composed from each finding's clause, ordered by
 * severity. Exact matching is why the composed path is the main path and not a
 * fallback nobody reads — a third finding is common.
 *
 * Two jobs here:
 *
 *   1. `enumerateFindingSets` — which sets this tree can actually produce. The
 *      combinations tab lists them, so an author writes rules for sets that
 *      occur rather than guessing.
 *   2. `foldFindings` — the card one set produces. The combinations tab
 *      previews it and the mock dry run returns it, so what the tab shows and
 *      what the dry run shows come from one function.
 */

import {
  betaNodeKind,
  outgoingEdges,
  readCombinations,
  type BetaTreeDoc,
  type CombinationRule,
} from "./betaTree";
import {
  findingSetKey,
  worstSeverity,
  worstStatus,
  type ActionType,
  type FindingSeverity,
  type FindingStatus,
} from "./betaConstants";

/** One catalogue row, as the fold needs it. */
export interface FoldFinding {
  code: string;
  clause_en: string;
  clause_ar: string;
  name_en: string;
  name_ar: string;
  default_status: FindingStatus;
  source: "platform" | "tenant";
}

export interface FoldedCard {
  /** Sorted codes — the identity, used three ways (section 5.1). */
  finding_set: string[];
  severity: FindingSeverity | null;
  status: FindingStatus;
  action_type: ActionType | null;
  text_en: string;
  text_ar: string;
  /** Null when the text was composed. */
  matched_rule: CombinationRule | null;
  /** Codes in the set that no catalogue resolves. */
  unresolved: string[];
}

/** The action type a composed card takes: the one from the highest-severity
 *  finding. The catalogue has no action type of its own, so the register node's
 *  severity ranking decides and the caller supplies the map. */
export interface ComposeContext {
  findings: ReadonlyMap<string, FoldFinding>;
  /** Severity the tree registers each code at, highest wins. */
  severityByCode: ReadonlyMap<string, FindingSeverity>;
  /** Action type per code, when the tree declares one. Composed cards with
   *  nothing to go on carry null and the Action Center files them as
   *  unclassified. */
  actionTypeByCode?: ReadonlyMap<string, ActionType>;
}

const AR_JOIN = "، ";
const AR_LAST_JOIN = " و";
const EN_JOIN = ", ";
const EN_LAST_JOIN = " and ";

/** Join clauses the way each language joins a list. Arabic uses the Arabic
 *  comma and joins the last item with "و" written against the word. */
export function joinClauses(clauses: readonly string[], lang: "en" | "ar"): string {
  const parts = clauses.filter((c) => c.trim() !== "");
  if (parts.length === 0) return "";
  if (parts.length === 1) return parts[0];
  const head = parts.slice(0, -1);
  const tail = parts[parts.length - 1];
  return lang === "ar"
    ? `${head.join(AR_JOIN)}${AR_LAST_JOIN}${tail}`
    : `${head.join(EN_JOIN)}${EN_LAST_JOIN}${tail}`;
}

/** One card from one finding set. */
export function foldFindings(
  codes: readonly string[],
  rules: readonly CombinationRule[],
  ctx: ComposeContext,
): FoldedCard {
  const set = [...new Set(codes)].sort();
  const key = findingSetKey(set);
  const matched = rules.find((r) => findingSetKey(r.codes) === key) ?? null;

  const severities = set
    .map((c) => ctx.severityByCode.get(c))
    .filter((s): s is FindingSeverity => s !== undefined);
  const severity = worstSeverity(severities);

  const resolved = set
    .map((c) => ctx.findings.get(c))
    .filter((f): f is FoldFinding => f !== undefined);
  const unresolved = set.filter((c) => !ctx.findings.has(c));

  // Order the clauses by severity, highest first, then by code so the same
  // set always reads the same way.
  const ordered = [...resolved].sort((a, b) => {
    const sa = ctx.severityByCode.get(a.code);
    const sb = ctx.severityByCode.get(b.code);
    const ra = sa ? SEVERITY_ORDER[sa] : -1;
    const rb = sb ? SEVERITY_ORDER[sb] : -1;
    if (ra !== rb) return rb - ra;
    return a.code.localeCompare(b.code);
  });

  const status = matched ? matched.status : worstStatus(resolved.map((f) => f.default_status));

  const topCode = ordered[0]?.code;
  const action_type = matched
    ? matched.action_type
    : topCode
      ? (ctx.actionTypeByCode?.get(topCode) ?? null)
      : null;

  return {
    finding_set: set,
    severity,
    status,
    action_type,
    text_en: matched
      ? matched.text_en
      : joinClauses(
          ordered.map((f) => f.clause_en),
          "en",
        ),
    text_ar: matched
      ? matched.text_ar
      : joinClauses(
          ordered.map((f) => f.clause_ar),
          "ar",
        ),
    matched_rule: matched,
    unresolved,
  };
}

const SEVERITY_ORDER: Record<FindingSeverity, number> = { info: 0, warning: 1, critical: 2 };

export interface EnumeratedSet {
  /** Sorted codes. An empty array is the "no card" route (section 5.1). */
  codes: string[];
  key: string;
  /** A rule matches this set exactly. */
  hasRule: boolean;
}

export interface EnumerateResult {
  sets: EnumeratedSet[];
  /** True when the walk hit its cap and the list is a sample, not the whole
   *  answer. The tab says so rather than presenting a partial list as final. */
  truncated: boolean;
}

/**
 * Every finding set this tree can produce.
 *
 * Walks (node, set-so-far) states. A branch that revisits a state adds nothing,
 * so a cycle terminates. The cap bounds a tree whose branches multiply; past it
 * the caller is told the list is partial.
 */
export function enumerateFindingSets(
  doc: BetaTreeDoc | null,
  options: { limit?: number } = {},
): EnumerateResult {
  const limit = options.limit ?? 2000;
  if (!doc?.root || !doc.nodes?.[doc.root]) return { sets: [], truncated: false };
  const nodes = doc.nodes;
  const rules = readCombinations(doc);
  const ruleKeys = new Set(rules.map((r) => findingSetKey(r.codes)));

  const seen = new Set<string>();
  const found = new Map<string, string[]>();
  let truncated = false;

  const stack: Array<{ id: string; codes: string[] }> = [{ id: doc.root, codes: [] }];
  let visits = 0;
  while (stack.length > 0) {
    if (visits++ > limit) {
      truncated = true;
      break;
    }
    const { id, codes } = stack.pop()!;
    const node = nodes[id];
    if (!node) continue;
    const kind = betaNodeKind(node);
    const nextCodes =
      kind === "register" && node.register?.code
        ? [...new Set([...codes, node.register.code])].sort()
        : codes;
    const stateKey = `${id}|${nextCodes.join("+")}`;
    if (seen.has(stateKey)) continue;
    seen.add(stateKey);

    if (kind === "stop") {
      found.set(findingSetKey(nextCodes), nextCodes);
      continue;
    }
    for (const edge of outgoingEdges(node)) {
      if (nodes[edge.to]) stack.push({ id: edge.to, codes: nextCodes });
    }
  }

  const sets = [...found.entries()]
    .map(([key, codes]) => ({ key, codes, hasRule: ruleKeys.has(key) }))
    // Biggest sets last: a reader scans the small ones first, and the empty
    // set — "nothing found" — is the first row.
    .sort((a, b) => a.codes.length - b.codes.length || a.key.localeCompare(b.key));
  return { sets, truncated };
}

/** Rules that match no set this tree can produce. They are not a publish
 *  rejection — an author may write ahead of the graph — but the tab flags
 *  them, because a rule that can never fire reads as working copy. */
export function orphanRules(
  rules: readonly CombinationRule[],
  sets: readonly EnumeratedSet[],
): CombinationRule[] {
  const producible = new Set(sets.map((s) => s.key));
  return rules.filter((r) => !producible.has(findingSetKey(r.codes)));
}

/**
 * Catalogue rows in the shape the fold wants, platform winning over tenant.
 *
 * Tenant rows go in first and platform rows overwrite them, which is the
 * resolution order section 6.2 describes: a tenant code shadowed by a platform
 * one is never read.
 */
export function foldCatalogueOf(
  findings: readonly {
    code: string;
    clause_en: string;
    clause_ar: string;
    name_en: string;
    name_ar: string;
    default_status: FindingStatus;
    source: "platform" | "tenant";
  }[],
): Map<string, FoldFinding> {
  const out = new Map<string, FoldFinding>();
  const ordered = [
    ...findings.filter((f) => f.source === "tenant"),
    ...findings.filter((f) => f.source === "platform"),
  ];
  for (const f of ordered) {
    out.set(f.code, {
      code: f.code,
      clause_en: f.clause_en,
      clause_ar: f.clause_ar,
      name_en: f.name_en,
      name_ar: f.name_ar,
      default_status: f.default_status,
      source: f.source,
    });
  }
  return out;
}
