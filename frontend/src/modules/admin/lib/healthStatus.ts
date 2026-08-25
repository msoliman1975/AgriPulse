import { differenceInHours, parseISO } from "date-fns";

export type Status = "ok" | "warn" | "crit" | "neutral";

export type Stream = "weather" | "imagery";

/**
 * How long a stream may go without a sync before this rollup calls it stale
 * or failing, in hours.
 *
 * These mirror `platform_alert_*_hours` in `backend/app/core/settings.py`,
 * and `platformHealthThresholds.test.ts` fails if they drift. Copying them
 * is what stops this page and the Platform alerts page from disagreeing
 * about the same tenant.
 *
 * The old rule was one fixed 24h ceiling for both streams. Weather arrives
 * every few hours, so 24h is about right for it. Imagery arrives when a
 * satellite passes: Sentinel-2 revisits every 2-5 days and a clouded pass is
 * rejected outright, so a four-day gap is an ordinary week, not a fault. On
 * 2026-08-25 that rule showed agrosina as "Failing" with zero failed jobs
 * and no matching platform alert, which is the false alarm this page exists
 * to rule out.
 *
 * Imagery uses the optical ceiling rather than the thermal one. The column
 * mixes both products, and the tighter of the two is the one worth reporting.
 */
export const AGE_HOURS: Record<Stream, { warn: number; crit: number }> = {
  weather: { warn: 26, crit: 50 },
  imagery: { warn: 144, crit: 240 },
};

export function statusFor(
  stream: Stream,
  lastSyncIso: string | null,
  failed24h: number,
  activeSubs: number,
): Status {
  if (activeSubs === 0) return "neutral";
  if (failed24h > 0) return "crit";
  if (!lastSyncIso) return "crit";
  const hours = differenceInHours(new Date(), parseISO(lastSyncIso));
  const { warn, crit } = AGE_HOURS[stream];
  if (hours >= crit) return "crit";
  if (hours >= warn) return "warn";
  return "ok";
}
