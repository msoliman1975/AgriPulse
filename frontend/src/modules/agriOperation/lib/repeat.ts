// Labels for when a manual task happens: the weeks it spans and how often it
// repeats inside them (public 0115). Pure.

type T = (key: string, opts?: Record<string, unknown>) => string;

/** "Wk 27" for a task inside one week, "Wk 27–39" for one that spans weeks. */
export function weekSpanLabel(
  week: number | null,
  durationDays: number,
  totalWeeks: number,
  t: T,
): string {
  if (week === null) return "—";
  const last = Math.min(totalWeeks, week + Math.floor((Math.max(1, durationDays) - 1) / 7));
  return last > week
    ? t("manual.weekSpan", { from: week, to: last })
    : t("manual.weekShort", { n: week });
}

/** "2× a week", "monthly", "2 times in the window"; null for a task done once. */
export function repeatLabel(
  count: number | null | undefined,
  unit: string | null | undefined,
  t: T,
): string | null {
  if (!count || !unit) return null;
  return t(`manual.repeat.${unit}`, { count });
}
