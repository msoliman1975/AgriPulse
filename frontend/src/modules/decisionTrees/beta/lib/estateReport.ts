/**
 * Pure helpers for the estate dry run screen.
 *
 * Sorting, formatting and the one judgement the screen makes: whether a
 * report is worth acting on or whether its error count says the tree cannot
 * be switched on yet. Kept out of the page so both can be unit tested without
 * rendering anything.
 *
 * **Numbers, never adjectives.** Every helper here returns a number or a
 * formatted number. "87.7 percent" is an answer; "most" is not.
 */

import type { EstateFindingSet, EstateReport } from "./estateApi";

export type SetSortKey = "count" | "label" | "rule";
export type SortDirection = "asc" | "desc";

/**
 * The finding-set table, sorted.
 *
 * Count descending is the default because that is the order section 9 prints
 * and the order an agronomist reads: the set that happens most is the one
 * whose text matters most. The label and rule orders exist because the table
 * is sortable by column.
 */
export function sortFindingSets(
  sets: readonly EstateFindingSet[],
  key: SetSortKey,
  direction: SortDirection,
): EstateFindingSet[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...sets].sort((a, b) => {
    if (key === "count") {
      if (a.count !== b.count) return sign * (a.count - b.count);
      return a.label.localeCompare(b.label);
    }
    if (key === "label") return sign * a.label.localeCompare(b.label);
    // Composed rows sort together, after the rules, then by rule name.
    const left = a.matched_rule ?? "";
    const right = b.matched_rule ?? "";
    if (left === right) return b.count - a.count;
    if (left === "") return sign;
    if (right === "") return -sign;
    return sign * left.localeCompare(right);
  });
}

/** Milliseconds as seconds with one decimal, or milliseconds under a second. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Milliseconds per cell, to one decimal. The sweep-cost number. */
export function formatPerCell(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return `${ms.toFixed(1)} ms`;
}

/** A count with thousands separators, in the reader's locale. */
export function formatCount(value: number | null | undefined, locale: string): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(locale).format(value);
}

/** One decimal place, always, so 88 and 87.7 line up in a column. */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}%`;
}

/**
 * How loudly the screen says something about the errors.
 *
 * The design makes the error count the headline of the report, not a
 * footnote: a switch on a missing index stops the walk, and cloud cover makes
 * a missing index common, so a tenant can be blanked before it is ever
 * switched on. The three bands are where a reader's decision changes:
 *
 *   none     no cell errored.
 *   some     under one cell in twenty. Worth reading the node list.
 *   blocking one cell in twenty or more. The tree is not ready.
 */
export type ErrorBand = "none" | "some" | "blocking";

export const BLOCKING_ERROR_PCT = 5;

export function errorBand(report: EstateReport): ErrorBand {
  const errored = report.cells_errored ?? 0;
  if (errored === 0) return "none";
  const pct = report.cells_errored_pct ?? 0;
  return pct >= BLOCKING_ERROR_PCT ? "blocking" : "some";
}

/**
 * Whether the combination rules are earning their place.
 *
 * Matching is exact, so a third finding sends the fold to composition and
 * composition is the main path. A composed share at 100 percent with rules
 * defined means every rule the author wrote is being bypassed, which is the
 * case the design asks the report to surface.
 */
export function rulesAreBypassed(report: EstateReport): boolean {
  const defined = report.rules_defined ?? 0;
  if (defined === 0) return false;
  return (report.rules_fired ?? 0) === 0 && (report.cells_carded ?? 0) > 0;
}

/** `{dry, ndvi_low}` from the codes, for a row that carries codes only. */
export function setLabel(codes: readonly string[]): string {
  if (codes.length === 0) return "{}";
  return `{${[...codes].sort().join(", ")}}`;
}
