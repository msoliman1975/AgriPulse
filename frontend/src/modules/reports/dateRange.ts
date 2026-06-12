// Pure date-range helpers for the Reports surface. Kept out of the
// DateRangePicker component file so that module exports only a
// component (react-refresh/only-export-components).

export interface DateRange {
  /** ISO timestamps (UTC) for the inclusive report window. */
  since: string;
  until: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Convert an ISO timestamp to the `yyyy-mm-dd` a date input wants. */
export function toDateInput(iso: string): string {
  return iso.slice(0, 10);
}

/** A `yyyy-mm-dd` date-input value → ISO at start (00:00) or end
 * (23:59:59.999) of that UTC day, so the window stays inclusive. */
export function fromDateInput(value: string, edge: "start" | "end"): string {
  const time = edge === "start" ? "T00:00:00.000Z" : "T23:59:59.999Z";
  return new Date(`${value}${time}`).toISOString();
}

/** A range covering the last `days` days ending now. */
export function presetRange(days: number): DateRange {
  const until = new Date();
  const since = new Date(until.getTime() - days * DAY_MS);
  return { since: since.toISOString(), until: until.toISOString() };
}

/** The default range a report opens on — last 30 days, matching the
 * backend's default window. */
export function defaultRange(): DateRange {
  return presetRange(30);
}
