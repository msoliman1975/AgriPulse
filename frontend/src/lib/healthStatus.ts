import { differenceInHours, parseISO } from "date-fns";

export type Status = "ok" | "warn" | "crit" | "neutral";

export type Stream = "weather" | "imagery";

/**
 * How long a stream may go without a sync before this rollup calls it stale
 * or failing, in hours.
 *
 * These mirror `platform_alert_*_hours` in `backend/app/core/settings.py`,
 * and `healthStatus.test.ts` fails if they drift. Copying them is what stops
 * the health pages and the Platform alerts page from disagreeing about the
 * same tenant.
 *
 * Both health pages call this. They each had their own copy of the rule and
 * both copies were wrong the same way, so a fix applied to one left the
 * other saying the opposite about the same farm on the same afternoon.
 *
 * The old rule was one fixed 24h ceiling for both streams. Weather arrives
 * every few hours, so 24h is about right for it. Imagery arrives when a
 * satellite passes: Sentinel-2 revisits every 2-5 days and a clouded pass is
 * rejected outright, so a four-day gap is an ordinary week, not a fault. On
 * 2026-08-25 that rule showed agrosina as "Failing" with zero failed jobs
 * and no matching platform alert, which is the false alarm these pages exist
 * to rule out.
 *
 * Imagery uses the optical ceiling rather than the thermal one. The column
 * mixes both products, and the tighter of the two is the one worth reporting.
 */
export const AGE_HOURS: Record<Stream, { warn: number; crit: number }> = {
  weather: { warn: 26, crit: 50 },
  imagery: { warn: 144, crit: 240 },
};

/**
 * `lastFailedIso` is optional. The per-tenant page has a
 * `weather_last_failed_at` column and warns when the newest attempt failed
 * within the day, even if a later one succeeded. The cross-tenant rollup has
 * no such column, so it passes null.
 */
export function statusFor(
  stream: Stream,
  lastSyncIso: string | null,
  failed24h: number,
  activeSubs: number,
  lastFailedIso: string | null = null,
): Status {
  if (activeSubs === 0) return "neutral";
  if (failed24h > 0) return "crit";
  if (!lastSyncIso) return "crit";
  const now = new Date();
  const hours = differenceInHours(now, parseISO(lastSyncIso));
  const { warn, crit } = AGE_HOURS[stream];
  if (hours >= crit) return "crit";
  if (hours >= warn) return "warn";
  if (lastFailedIso !== null && differenceInHours(now, parseISO(lastFailedIso)) < 24) {
    return "warn";
  }
  return "ok";
}
