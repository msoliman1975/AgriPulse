// When a repeating manual task falls inside its window (public 0115). The
// same rule as the server's occurrence_offsets (allocation.py), so the
// Catalog counts the times in each week the way a saved plan schedules them.
// Pure.

const UNIT_DAYS: Record<string, number> = { week: 7, month: 365.25 / 12 };
const MAX_OCCURRENCES = 400;

/** Day offsets from the window start for each time the task is done. */
export function occurrenceOffsets(
  durationDays: number,
  repeatCount: number | null | undefined,
  repeatUnit: string | null | undefined,
): number[] {
  const window = Math.max(1, Math.floor(durationDays || 1));
  if (!repeatCount || !repeatUnit) return [0];
  if (repeatUnit === "season") {
    const step = window / repeatCount;
    return [...new Set(Array.from({ length: repeatCount }, (_, i) => Math.floor(i * step)))].sort(
      (a, b) => a - b,
    );
  }
  const unitDays = UNIT_DAYS[repeatUnit];
  if (!unitDays) return [0];
  const step = unitDays / repeatCount;
  const out: number[] = [];
  for (let i = 0; out.length < MAX_OCCURRENCES; i += 1) {
    const day = Math.floor(i * step);
    if (day >= window) break;
    if (out[out.length - 1] !== day) out.push(day);
  }
  return out.length ? out : [0];
}
