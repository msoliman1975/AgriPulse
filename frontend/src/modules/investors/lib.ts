import type { HoldingStatus, InvestorStatus } from "@/api/investors";
import { isApiError } from "@/api/errors";
import type { PillKind } from "@/components/Pill";

/** React Query key for one block's holdings; the detail page shares it. */
export const blockHoldingsKey = (farmId: string, blockId: string) =>
  ["holdings", "block", farmId, blockId] as const;

/** The server's own sentence when there is one; the rules are explained there. */
export function errorText(err: unknown): string {
  if (isApiError(err)) return err.problem.detail ?? err.problem.title ?? String(err);
  return err instanceof Error ? err.message : String(err);
}

export const INVESTOR_STATUS_PILL: Record<InvestorStatus, PillKind> = {
  not_invited: "neutral",
  invited: "info",
  active: "ok",
  suspended: "warn",
  archived: "neutral",
};

export const HOLDING_STATUS_PILL: Record<HoldingStatus, PillKind> = {
  draft: "neutral",
  available: "info",
  sold: "ok",
  archived: "neutral",
};

/** Fill colours for the holdings map, by derived status. */
export const HOLDING_STATUS_COLOR: Record<HoldingStatus, string> = {
  draft: "#94a3b8",
  available: "#3b82f6",
  sold: "#f59e0b",
  archived: "#cbd5e1",
};

export function formatPct(value: string | number, locale: string): string {
  const n = typeof value === "number" ? value : Number(value);
  return new Intl.NumberFormat(locale === "ar" ? "ar-u-nu-latn" : locale, {
    maximumFractionDigits: 2,
  }).format(n);
}

/** ISO date (YYYY-MM-DD) for a date input, in local time. */
export function isoDay(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** The day before an ISO date, as an ISO date. */
export function dayBefore(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDay(new Date(y, m - 1, d - 1));
}
