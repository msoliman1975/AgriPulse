import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  getWeatherIndexCatalog,
  getWeatherIndexSummary,
  type WeatherIndexCatalogItem,
  type WeatherIndexSummaryEntry,
} from "@/api/weatherIndices";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import i18n from "@/i18n";

import { WeatherIndexChart } from "./WeatherIndexChart";

interface Props {
  farmId: string;
}

/**
 * Farm-level weather-index strip for the Insights overview: one card per
 * index with its current value, anomaly vs the seasonal normal, and a
 * 7-day trend. Clicking a card expands the 90-day series with a
 * climatology band. Weather is farm-centroid data, so this is a temporal
 * surface — deliberately not a per-cell map overlay.
 */
export function WeatherIndicesStrip({ farmId }: Props): ReactNode {
  const { t } = useTranslation("weatherIndices");
  const isAr = i18n.language === "ar";
  const [selected, setSelected] = useState<string | null>(null);

  const catalogQ = useQuery({
    queryKey: ["weatherIndices", "catalog"] as const,
    queryFn: getWeatherIndexCatalog,
    staleTime: 5 * 60_000,
  });
  const summaryQ = useQuery({
    queryKey: ["weatherIndices", "summary", farmId] as const,
    queryFn: () => getWeatherIndexSummary(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  const catalogByCode = useMemo(() => {
    const map = new Map<string, WeatherIndexCatalogItem>();
    for (const item of catalogQ.data ?? []) map.set(item.code, item);
    return map;
  }, [catalogQ.data]);

  const nameFor = (code: string): string => {
    const c = catalogByCode.get(code);
    if (!c) return code;
    return (isAr ? c.name_ar : c.name_en) ?? c.name_en;
  };
  const unitFor = (code: string): string => {
    const unit = catalogByCode.get(code)?.unit ?? "";
    // Wind ships "m/s, °"; show only the leading magnitude unit on cards.
    return unit.split(",")[0].trim();
  };

  const loading = catalogQ.isLoading || summaryQ.isLoading;
  const hasError = catalogQ.isError || summaryQ.isError;
  const entries = summaryQ.data?.indices ?? [];

  return (
    <Card noPadding className="p-4" aria-labelledby="weather-indices-heading">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2
          id="weather-indices-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("strip.title")}
        </h2>
        <span className="text-[11px] text-ap-muted">{t("strip.subtitle")}</span>
      </header>

      <div className="mt-3">
        {loading ? (
          <Skeleton className="h-24 w-full" />
        ) : hasError ? (
          <p className="py-8 text-center text-sm text-ap-crit">{t("strip.loadFailed")}</p>
        ) : entries.length === 0 ? (
          <p className="py-8 text-center text-sm text-ap-muted">{t("strip.empty")}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {entries.map((entry) => (
                <IndexCard
                  key={entry.index_code}
                  entry={entry}
                  name={nameFor(entry.index_code)}
                  unit={unitFor(entry.index_code)}
                  selected={selected === entry.index_code}
                  onSelect={() =>
                    setSelected((cur) => (cur === entry.index_code ? null : entry.index_code))
                  }
                />
              ))}
            </div>
            {selected ? (
              <WeatherIndexChart
                farmId={farmId}
                indexCode={selected}
                name={nameFor(selected)}
                unit={unitFor(selected)}
              />
            ) : null}
          </>
        )}
      </div>
    </Card>
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
  const value = _toNum(entry.value);
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
        <AnomalyChip zscore={_toNum(entry.zscore)} />
        <Trend delta={_toNum(entry.trend_7d_delta)} unit={unit} />
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
  // High/Low label + the signed σ value, so we stay on the ap-* tokens.
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
  const up = delta > 0;
  return (
    <span
      className={`text-[10px] tabular-nums ${up ? "text-ap-good" : "text-ap-crit"}`}
      title={t("trend.label")}
    >
      {up ? "↑" : "↓"} {up ? "+" : ""}
      {delta.toFixed(1)}
      {u}
    </span>
  );
}

function _toNum(v: string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
