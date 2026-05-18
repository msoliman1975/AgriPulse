import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { getFarm } from "@/api/farms";
import { listBlocks, type Block } from "@/api/blocks";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { WeatherForecastPanel } from "@/modules/weather/components/WeatherForecastPanel";
import { BlockHealthScorecard } from "../components/BlockHealthScorecard";
import { FarmTrendChart } from "../components/FarmTrendChart";
import { KPICards } from "../components/KPICards";

// Track B.1 — Insights as "Farm health overview".
//
// Read-only, analytical, season-scale. Triage widgets
// (AlertsFeedCard, LatestSignalsCard, UpcomingActivitiesCard,
// LandUnitHealthTable) live on their own dedicated pages now; KPI cards
// still link to them so they remain discoverable. The "New plan" CTA
// belongs to /plan, not here.
//
// B.2 swaps the single-block TrendChartCard for FarmTrendChart
// (multi-block timeseries from /farms/{id}/index-timeseries) +
// BlockHealthScorecard (per-block rollup from /farms/{id}/health-
// summary).
export function InsightsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("insights");
  const dateLocale = useDateLocale();
  const { data: farm, isLoading } = useQuery({
    queryKey: ["farms", "detail", farmId] as const,
    queryFn: () => getFarm(farmId!),
    enabled: Boolean(farmId),
  });
  const canReadWeather = useCapability("weather.read", { farmId });

  // WeatherForecastPanel keys on block_id but resolves to the farm
  // centroid internally; pulling the first block is the existing
  // contract. When B.2's farm-level weather summary lands this can drop.
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

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex items-start gap-3">
        <img
          src="/agripulse-mark.png"
          alt="AgriPulse"
          className="h-12 w-12 shrink-0 object-contain"
        />
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
          <div className="mt-1 text-sm text-ap-muted">
            {isLoading ? (
              <Skeleton className="inline-block h-4 w-64" />
            ) : (
              <>
                <span className="font-medium text-ap-ink">{farm?.name ?? "—"}</span>
                {farm ? (
                  <>
                    {" · "}
                    {Number(farm.area_value ?? 0).toFixed(1)} {farm.area_unit}
                    {" · "}
                    {format(new Date(), "EEEE, MMMM d", { locale: dateLocale })}
                  </>
                ) : null}
              </>
            )}
          </div>
        </div>
      </header>

      <KPICards farmId={farmId} />

      <FarmTrendChart farmId={farmId} />

      <BlockHealthScorecard farmId={farmId} />

      {canReadWeather && firstBlock ? (
        <WeatherForecastPanel
          blockId={firstBlock.id}
          farmId={farmId}
          farmName={farm?.name ?? null}
        />
      ) : null}
    </div>
  );
}
