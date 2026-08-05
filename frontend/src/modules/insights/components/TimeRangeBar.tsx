import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { customRange, isCustom, presetRange, type TimeRange } from "../lib/timeRange";
import { TimeSpanChips, type TimeSpanKey } from "./TimeSpanChips";

interface Props {
  value: TimeRange;
  onChange: (next: TimeRange) => void;
}

/**
 * The overview's single time control: presets plus an explicit From→To.
 *
 * It sits once under the page header rather than inside each card, so the
 * vegetation trend, the weather strip, the weather trend and the outlook can
 * no longer disagree about which window the reader is looking at.
 *
 * Picking a preset clears a custom range and vice versa — they are two ways
 * of saying the same thing, and showing both as active would leave it
 * ambiguous which one the charts obeyed.
 */
export function TimeRangeBar({ value, onChange }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const custom = isCustom(value);

  const setEnd = (which: "from" | "to", day: string): void => {
    const from = which === "from" ? day : (custom ? value.from : null) ?? "";
    const to = which === "to" ? day : (custom ? value.to : null) ?? "";
    // A half-filled pair is not a range yet; hold it without disturbing the
    // charts, which keep obeying the preset until both ends are valid.
    if (from && to && from <= to) {
      onChange(customRange(from, to));
      return;
    }
    onChange({ span: "custom", from: from || null, to: to || null });
  };

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2"
      role="region"
      aria-label={t("range.regionLabel")}
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-ap-muted">
        {t("range.label")}
      </span>

      <TimeSpanChips
        // With a custom range active no preset should read as selected —
        // pass a value outside the option set.
        value={custom ? ("" as TimeSpanKey) : (value.span as TimeSpanKey)}
        onChange={(next) => onChange(presetRange(next))}
      />

      <label className="flex items-center gap-1 text-[11px] text-ap-muted">
        <span>{t("trend.range.from")}</span>
        <input
          type="date"
          value={custom ? (value.from ?? "") : ""}
          max={custom ? (value.to ?? undefined) : undefined}
          onChange={(e) => setEnd("from", e.target.value)}
          className="rounded-md border border-ap-line bg-white px-1.5 py-0.5 text-[11px] text-ap-ink"
        />
      </label>
      <label className="flex items-center gap-1 text-[11px] text-ap-muted">
        <span>{t("trend.range.to")}</span>
        <input
          type="date"
          value={custom ? (value.to ?? "") : ""}
          min={custom ? (value.from ?? undefined) : undefined}
          onChange={(e) => setEnd("to", e.target.value)}
          className="rounded-md border border-ap-line bg-white px-1.5 py-0.5 text-[11px] text-ap-ink"
        />
      </label>

      {custom ? (
        <button
          type="button"
          onClick={() => onChange(presetRange("90d"))}
          className="text-[11px] font-medium text-ap-primary hover:underline"
        >
          {t("trend.range.clear")}
        </button>
      ) : null}
    </div>
  );
}
