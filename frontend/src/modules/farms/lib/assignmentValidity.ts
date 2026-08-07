// Pure valid-time helpers for the assignment panel.
//
// Mirrors `backend/app/modules/farms/validity.py`. The server is authoritative
// — it re-checks every write and the DB holds an exclusion constraint — but the
// panel has to say *before* you save what a new range will do: which assignment
// it closes, and which one it would collide with.
//
// The range is half-open, `[from, to)`. The last day under a crop is the day
// before `to`, which is what lets one assignment end and the next start on the
// same date without overlapping. An off-by-one here and the panel would refuse
// a perfectly ordinary handover.

import type { BlockCropAssignment } from "@/api/cropAssignments";

/** ISO `YYYY-MM-DD` for today, in the user's timezone. */
export function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function isActiveOn(a: BlockCropAssignment, on: string): boolean {
  if (!a.effective_from || a.effective_from > on) return false;
  return a.effective_to === null || a.effective_to > on;
}

export function currentAssignment(
  rows: BlockCropAssignment[],
  on: string,
): BlockCropAssignment | null {
  const matches = rows.filter((r) => isActiveOn(r, on));
  if (!matches.length) return null;
  return matches.reduce((a, b) => (a.effective_from >= b.effective_from ? a : b));
}

export type ValidityState = "past" | "current" | "scheduled";

export function stateOn(a: BlockCropAssignment, on: string): ValidityState {
  if (isActiveOn(a, on)) return "current";
  return a.effective_from > on ? "scheduled" : "past";
}

/** Half-open overlap, mirroring the DB's `daterange && daterange`. */
export function overlaps(
  aFrom: string,
  aTo: string | null,
  bFrom: string,
  bTo: string | null,
): boolean {
  const aEndsFirst = aTo !== null && aTo <= bFrom;
  const bEndsFirst = bTo !== null && bTo <= aFrom;
  return !(aEndsFirst || bEndsFirst);
}

/** The ongoing assignment a new one starting at `from` would close.
 *
 *  Only an open-ended row that already started — closing a *bounded* one would
 *  silently rewrite a period the user set an end date for on purpose. */
export function openAssignmentToClose(
  rows: BlockCropAssignment[],
  from: string,
): BlockCropAssignment | null {
  const candidates = rows.filter((r) => r.effective_to === null && r.effective_from <= from);
  if (!candidates.length) return null;
  return candidates.reduce((a, b) => (a.effective_from >= b.effective_from ? a : b));
}

/** The first assignment a proposed range would collide with, skipping the one
 *  that is about to be auto-closed (it becomes adjacent, not overlapping). */
export function findConflict(
  rows: BlockCropAssignment[],
  from: string,
  to: string | null,
  closingId: string | null,
): BlockCropAssignment | null {
  return (
    rows.find((r) => r.id !== closingId && overlaps(r.effective_from, r.effective_to, from, to)) ??
    null
  );
}

/** Fallow stretches between consecutive assignments — a real state that two
 *  non-touching dates communicate only by arithmetic. */
export function gaps(rows: BlockCropAssignment[]): { from: string; to: string }[] {
  const ordered = [...rows].sort((a, b) => (a.effective_from < b.effective_from ? -1 : 1));
  const out: { from: string; to: string }[] = [];
  for (let i = 0; i < ordered.length - 1; i += 1) {
    const end = ordered[i].effective_to;
    const nextStart = ordered[i + 1].effective_from;
    if (end && end < nextStart) out.push({ from: end, to: nextStart });
  }
  return out;
}

/** Whole days between two ISO dates. */
export function dayCount(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

/** "7y 5m" / "4m" / "12d" — a duration a grower can read at a glance. */
export function humanDuration(from: string, to: string | null): string {
  const n = dayCount(from, to ?? todayIso());
  if (n < 0) return "—";
  if (n < 60) return `${n}d`;
  const years = Math.floor(n / 365);
  const months = Math.round((n % 365) / 30);
  if (years === 0) return `${months}m`;
  return months === 0 ? `${years}y` : `${years}y ${months}m`;
}
