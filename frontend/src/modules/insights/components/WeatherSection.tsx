import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listBlocks, type Block } from "@/api/blocks";
import {
  getWeatherIndexCatalog,
  getWeatherIndexSummary,
  type WeatherIndexCatalogItem,
} from "@/api/weatherIndices";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import i18n from "@/i18n";

import { pastDays as resolvePastDays, toDayRange, type TimeRange } from "../lib/timeRange";
import { WeatherNowStrip } from "./WeatherNowStrip";
import { WeatherOutlookPanel } from "./WeatherOutlookPanel";
import { WeatherRiskRow } from "./WeatherRiskRow";
import { WeatherTrendsPanel } from "./WeatherTrendsPanel";

interface Props {
  farmId: string;
  /** The overview's shared time range; the page owns it (see TimeRangeBar). */
  range: TimeRange;
  /** Caller has `weather_risk.read`; the risk row is a separate capability. */
  showRisk: boolean;
  /** Crop-filtered blocks, or null for the whole farm. Only the risk row can
   *  honour this: everything above it is farm-centroid data, one point for
   *  the whole farm, so there is no per-crop version of it to show. */
  blockIds?: readonly string[] | null;
}

// The outlook's past slice is a stitched daily chart, so "all" would render
// years of bars against a 7-day forecast. It clamps; the trend panel does not.
const OUTLOOK_MAX_PAST_DAYS = 90;

/**
 * All of the farm's weather in one section, read top to bottom: what it is
 * NOW, how it has MOVED, what is COMING, and what that is doing to the crop.
 *
 * These were four sibling cards on the overview — a stitched observed/forecast
 * chart, an index strip, a trends card and a risk widget — each with its own
 * heading, its own time-span control and its own loading state, three of them
 * reading the same weather_index_daily rows at different altitudes. A reader
 * scrolling the overview met the word "weather" four times and had to work out
 * why. One section, one time span, one story.
 *
 * The catalog and summary queries live here because the strip and the trend
 * panel both need them, and a farm should not pay for them twice.
 */
export function WeatherSection({ farmId, range, showRisk, blockIds = null }: Props): ReactNode {
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

  // The outlook endpoints key on block_id but resolve to the farm centroid
  // internally; pulling the first block is the existing farm-level contract.
  // When a farm-level weather endpoint lands, drop this.
  const [firstBlock, setFirstBlock] = useState<Block | null>(null);
  useEffect(() => {
    if (!farmId) return;
    let cancelled = false;
    void listBlocks(farmId)
      .then((page) => {
        if (cancelled) return;
        setFirstBlock(page.items[0] ?? null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  const indices = useMemo<WeatherIndexCatalogItem[]>(
    () => [...(catalogQ.data ?? [])].sort((a, b) => a.sort_order - b.sort_order),
    [catalogQ.data],
  );

  const catalogByCode = useMemo(() => {
    const map = new Map<string, WeatherIndexCatalogItem>();
    for (const item of indices) map.set(item.code, item);
    return map;
  }, [indices]);

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

  // "all" has no lower bound; the endpoint treats a missing `from` as
  // "everything stored".
  const dayRange = useMemo(() => toDayRange(range), [range]);
  const pastDays = useMemo(() => resolvePastDays(range, OUTLOOK_MAX_PAST_DAYS), [range]);

  const loading = catalogQ.isLoading || summaryQ.isLoading;
  const hasError = catalogQ.isError || summaryQ.isError;
  const entries = summaryQ.data?.indices ?? [];

  return (
    <Card as="section" aria-labelledby="weather-section-heading">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2
            id="weather-section-heading"
            className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
          >
            {t("section.title")}
          </h2>
          <p className="text-[11px] text-ap-muted">{t("section.subtitle")}</p>
        </div>
      </header>

      {loading ? (
        <Skeleton className="mt-3 h-24 w-full" />
      ) : hasError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("strip.loadFailed")}</p>
      ) : (
        <div className="mt-3 space-y-5">
          <WeatherNowStrip
            entries={entries}
            nameFor={nameFor}
            unitFor={unitFor}
            selected={selected}
            onSelect={(code) => setSelected((cur) => (cur === code ? null : code))}
          />

          <WeatherTrendsPanel
            farmId={farmId}
            indices={indices}
            from={dayRange.from}
            to={dayRange.to}
            selected={selected}
            onClearSelection={() => setSelected(null)}
          />

          {firstBlock ? (
            <WeatherOutlookPanel blockId={firstBlock.id} pastDays={pastDays} />
          ) : null}

          {showRisk ? <WeatherRiskRow farmId={farmId} blockIds={blockIds} /> : null}
        </div>
      )}
    </Card>
  );
}
