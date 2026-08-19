/**
 * When a due value actually runs out.
 *
 * Work arrives with two different shapes of deadline: a visit carries a
 * timestamp, board work carries a plain date. A date is due at the **end** of
 * that day — reading `2026-08-18` as midnight marks everything scheduled for
 * today as overdue at breakfast.
 *
 * This lives on its own because two callers need the same answer and they used
 * to disagree: the list grouped an activity under "Today" while the badge on
 * the same row read "overdue". One rule, one module.
 */
export function dueAtMs(due: string | null): number | null {
  if (!due) return null;
  if (!due.includes("T")) {
    // Local end of day, not UTC: the scout's day ends where they are standing.
    const [y, m, d] = due.split("-").map(Number);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d, 23, 59, 59, 999).getTime();
  }
  const ms = new Date(due).getTime();
  return Number.isNaN(ms) ? null : ms;
}
