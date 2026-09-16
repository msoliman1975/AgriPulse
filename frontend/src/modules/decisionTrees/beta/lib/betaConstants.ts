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
 * backend Literal and the CHECK constraint. Severity is read back from the
 * backend source in `betaConstants.test.ts`. The finding status has no backend
 * source in this branch yet — session 1 adds `decision_tree_findings` with its
 * CHECK — so its drift check is written and inert until that migration lands.
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

/** The health class a finding carries in the catalogue, and that a
 *  combination rule may override. The worst status wins. */
export const FINDING_STATUSES = ["normal", "watch", "stressed", "unknown"] as const;
export type FindingStatus = (typeof FINDING_STATUSES)[number];

/** Rank used to fold several findings into one health class. `unknown` ranks
 *  above `normal` but below a real problem: not knowing is worse than fine and
 *  better than measured stress. */
export const STATUS_RANK: Record<FindingStatus, number> = {
  normal: 0,
  unknown: 1,
  watch: 2,
  stressed: 3,
};

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

/** The worst status in a list. An empty set is `normal` — nothing was found. */
export function worstStatus(statuses: readonly FindingStatus[]): FindingStatus {
  let best: FindingStatus = "normal";
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
