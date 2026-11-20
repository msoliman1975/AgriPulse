// Label for how often a manual task repeats inside its window (public 0115). Pure.

type T = (key: string, opts?: Record<string, unknown>) => string;

/** "2× a week", "monthly", "2 times in the window"; null for a task done once. */
export function repeatLabel(
  count: number | null | undefined,
  unit: string | null | undefined,
  t: T,
): string | null {
  if (!count || !unit) return null;
  return t(`manual.repeat.${unit}`, { count });
}
