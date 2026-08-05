import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { WeatherIndexSummaryEntry } from "@/api/weatherIndices";

interface Props {
  entries: readonly WeatherIndexSummaryEntry[];
  /** Localized name for an index code, resolved by the section from the catalog. */
  nameFor: (code: string) => string;
  unitFor: (code: string) => string;
  selected: string | null;
  onSelect: (code: string) => void;
}

/**
 * The "what is it right now" row of the weather section: one card per index
 * with its current value, how far that sits from the seasonal normal, and
 * which way it has moved this week.
 *
 * Presentational — the section owns the catalog and summary queries, because
 * the trend panel below needs the same two answers and a farm should not pay
 * for them twice.
 *
 * Selecting a card drives the trend panel rather than expanding a chart here,
 * so the section never grows a second chart of the same series.
 */
export function WeatherNowStrip({
  entries,
  nameFor,
  unitFor,
  selected,
  onSelect,
}: Props): ReactNode {
  const { t } = useTranslation("weatherIndices");

  if (entries.length === 0) {
    return <p className="py-6 text-center text-sm text-ap-muted">{t("strip.empty")}</p>;
  }

  return (
    <div
      className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
      role="group"
      aria-label={t("strip.title")}
    >
      {entries.map((entry) => (
        <IndexCard
          key={entry.index_code}
          entry={entry}
          name={nameFor(entry.index_code)}
          unit={unitFor(entry.index_code)}
          selected={selected === entry.index_code}
          onSelect={() => onSelect(entry.index_code)}
        />
      ))}
    </div>
  );
}

function IndexCard({
  entry,
  name,
  unit,
  selected,
  onSelect,
}: {
  entry: WeatherIndexSummaryEntry;
  name: string;
  unit: string;
  selected: boolean;
  onSelect: () => void;
}): ReactNode {
  const value = toNum(entry.value);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex flex-col items-start gap-1 rounded-lg border p-2.5 text-start transition-colors ${
        selected ? "border-ap-ink bg-ap-bg" : "border-ap-line bg-ap-panel hover:border-ap-muted"
      }`}
    >
      <span className="line-clamp-2 text-[11px] font-medium text-ap-ink">{name}</span>
      <span className="text-lg font-semibold tabular-nums text-ap-ink">
        {value !== null ? value.toFixed(1) : "—"}
        {value !== null && unit ? <span className="ms-1 text-xs text-ap-muted">{unit}</span> : null}
      </span>
      <div className="flex w-full items-center justify-between">
        <AnomalyChip zscore={toNum(entry.zscore)} />
        <Trend delta={toNum(entry.trend_7d_delta)} unit={unit} />
      </div>
    </button>
  );
}

function AnomalyChip({ zscore }: { zscore: number | null }): ReactNode {
  const { t } = useTranslation("weatherIndices");
  if (zscore === null) {
    return <span className="text-[10px] text-ap-muted">—</span>;
  }
  const mag = Math.abs(zscore);
  const label = mag < 1 ? t("anomaly.normal") : zscore > 0 ? t("anomaly.high") : t("anomaly.low");
  // Severity by magnitude (neutral → warn → crit); the sign lives in the
  // High/Low label + the signed sigma value, so we stay on the ap-* tokens.
  let cls = "bg-ap-line text-ap-muted";
  if (mag >= 2) cls = "bg-ap-crit-soft text-ap-crit";
  else if (mag >= 1) cls = "bg-ap-warn-soft text-ap-warn";
  const signed = `${zscore > 0 ? "+" : ""}${zscore.toFixed(1)}σ`;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
      title={t("anomaly.aria", { z: signed })}
    >
      {label} {signed}
    </span>
  );
}

function Trend({ delta, unit }: { delta: number | null; unit: string }): ReactNode {
  const { t } = useTranslation("weatherIndices");
  if (delta === null) {
    return (
      <span className="text-[10px] text-ap-muted" title={t("trend.label")}>
        —
      </span>
    );
  }
  const u = unit ? ` ${unit}` : "";
  if (Math.abs(delta) < 0.05) {
    return (
      <span className="text-[10px] text-ap-muted" title={t("trend.label")}>
        ~
      </span>
    );
  }
  // Direction only — "up" is not good news for every index (a rising heat or
  // ET anomaly is the opposite), so the arrow carries the sign and the colour
  // stays neutral ink rather than implying a verdict.
  const up = delta > 0;
  return (
    <span className="text-[10px] tabular-nums text-ap-muted" title={t("trend.label")}>
      {up ? "↑" : "↓"} {up ? "+" : ""}
      {delta.toFixed(1)}
      {u}
    </span>
  );
}

function toNum(v: string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
