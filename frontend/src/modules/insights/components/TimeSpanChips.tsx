import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export type TimeSpanKey = "7d" | "30d" | "90d" | "season" | "all";

interface Props {
  value: TimeSpanKey;
  onChange: (next: TimeSpanKey) => void;
  /** Hide the "season" option when no season context is available. */
  options?: readonly TimeSpanKey[];
  /** Translation key prefix; defaults to "trend.timespan". */
  i18nPrefix?: string;
  ariaLabel?: string;
}

const DEFAULT_OPTIONS: readonly TimeSpanKey[] = ["7d", "30d", "90d", "season", "all"];

export function TimeSpanChips({
  value,
  onChange,
  options = DEFAULT_OPTIONS,
  i18nPrefix = "trend.timespan",
  ariaLabel,
}: Props): ReactNode {
  const { t } = useTranslation("insights");
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel ?? t(`${i18nPrefix}.ariaLabel`)}
      className="flex flex-wrap gap-1"
    >
      {options.map((opt) => {
        const active = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt)}
            className={
              "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors " +
              (active
                ? "bg-ap-accent text-white"
                : "border border-ap-line bg-white text-ap-muted hover:bg-ap-bg")
            }
          >
            {t(`${i18nPrefix}.${opt}`)}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Resolve a TimeSpanKey to a `since` ISO timestamp (open-ended `until`).
 * Returns `null` for "all" — callers should omit `since` from the API call
 * in that case.
 */
export function timeSpanToSince(key: TimeSpanKey, now: Date = new Date()): string | null {
  // Season is a stopgap: backend doesn't expose season_start yet, so we
  // use 180d as the typical Northern-hemisphere growing-season window.
  // When SeasonContextResponse gains real dates, swap this branch.
  const daysMap: Record<TimeSpanKey, number | null> = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    season: 180,
    all: null,
  };
  const days = daysMap[key];
  if (days === null) return null;
  const since = new Date(now);
  since.setDate(since.getDate() - days);
  return since.toISOString();
}
