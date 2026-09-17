/**
 * The closed vocabularies the beta designer offers.
 *
 * Three lists appear on both sides of the wire — severity, the finding health
 * status, and the action type. A mirrored list that drifts degrades the screen
 * with no error: the picker offers a value the backend CHECK rejects, or omits
 * one the engine emits, and nothing fails until an author hits it.
 *
 * So: the action type is not re-declared here at all, it is imported from
 * `@/lib/actionTypes`, which already fails a test when it drifts from the
 * backend Literal and the CHECK constraint. Severity and the status list are
 * read back from the backend source in `betaConstants.test.ts`.
 *
 * See docs/proposals/unified-decision-tree-engine.md sections 4.1 and 6.1.
 */

import { ACTION_TYPES, type ActionType } from "@/lib/actionTypes";

/** Severity carried by a `register` node. Mirrors the backend `Severity`
 *  Literal in `recommendations/schemas.py`. */
export const FINDING_SEVERITIES = ["info", "warning", "critical"] as const;
export type FindingSeverity = (typeof FINDING_SEVERITIES)[number];

/** Rank used to pick the card's severity: the highest among its findings. */
export const SEVERITY_RANK: Record<FindingSeverity, number> = {
  info: 0,
  warning: 1,
  critical: 2,
};

/**
 * The health class a finding carries in the catalogue.
 *
 * This is the platform's decision-tree status vocabulary, the same five codes
 * a leaf resolves to today and the same ones
 * `tenant_*.decision_tree_block_verdicts.status_code` is CHECK constrained to.
 * Not the reports module's `normal / watch / stressed / unknown`, which
 * classifies a baseline z-score and which no tree ever writes — picking that
 * one would have written a value the CHECK rejects.
 *
 * Mirrors `app.modules.recommendations.status_codes.STATUS_DEFINITIONS`.
 */
export const FINDING_STATUSES = ["na", "very_good", "good", "issue", "alert"] as const;
export type FindingStatus = (typeof FINDING_STATUSES)[number];

/**
 * Rank used to fold several findings into one health class: the worst wins.
 *
 * These are `StatusDefinition.rank` from the platform list, so "the worst
 * status wins" in a fold and "the highest rank wins" on a block's verdicts are
 * one ordering. `na` is rank 0, so a finding with nothing to say never
 * outranks a real answer.
 */
export const STATUS_RANK: Record<FindingStatus, number> = {
  na: 0,
  very_good: 1,
  good: 2,
  issue: 3,
  alert: 4,
};

/**
 * What an empty finding set resolves to.
 *
 * `very_good`, not `na`: the tree ran, walked every check, and none of them
 * fired. That is the strongest thing the fold can say, and it is not the same
 * as `na`, which means no tree had an opinion at all. Matches
 * `recommendations.findings.worst_status`.
 */
export const EMPTY_SET_STATUS: FindingStatus = "very_good";

/** Which table a finding code resolved from. The fold reads platform first. */
export const FINDING_SOURCES = ["platform", "tenant"] as const;
export type FindingSource = (typeof FINDING_SOURCES)[number];

/** Re-exported, never re-declared. */
export { ACTION_TYPES };
export type { ActionType };

export function isFindingSeverity(value: string): value is FindingSeverity {
  return (FINDING_SEVERITIES as readonly string[]).includes(value);
}

export function isFindingStatus(value: string): value is FindingStatus {
  return (FINDING_STATUSES as readonly string[]).includes(value);
}

/** The highest severity in a list, or null for an empty list. */
export function worstSeverity(severities: readonly FindingSeverity[]): FindingSeverity | null {
  let best: FindingSeverity | null = null;
  for (const s of severities) {
    if (best === null || SEVERITY_RANK[s] > SEVERITY_RANK[best]) best = s;
  }
  return best;
}

/** The worst status in a list. An empty list is `very_good` — see above. */
export function worstStatus(statuses: readonly FindingStatus[]): FindingStatus {
  if (statuses.length === 0) return EMPTY_SET_STATUS;
  let best: FindingStatus = statuses[0];
  for (const s of statuses) {
    if (STATUS_RANK[s] > STATUS_RANK[best]) best = s;
  }
  return best;
}

/** The identity of a finding set: the sorted codes. Used to pick a
 *  combination rule, to compare two sets, and as a React key. */
export function findingSetKey(codes: readonly string[]): string {
  return [...new Set(codes)].sort().join("+");
}
