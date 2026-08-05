import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { getFarm } from "@/api/farms";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { BlockHealthScorecard } from "../components/BlockHealthScorecard";
import { FarmTrendChart } from "../components/FarmTrendChart";
import { KPICards } from "../components/KPICards";
import { SeasonContextBar } from "../components/SeasonContextBar";
import { WeatherSection } from "../components/WeatherSection";

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
  const {
    data: farm,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["farms", "detail", farmId] as const,
    queryFn: () => getFarm(farmId!),
    enabled: Boolean(farmId),
  });
  const canReadWeather = useCapability("weather.read", { farmId });
  const canReadRisk = useCapability("weather_risk.read", { farmId });

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  // If the farm itself can't load, the whole overview is meaningless — show a
  // single error instead of a broken header over empty widgets.
  if (isError) {
    return (
      <Page>
        <ErrorState message={t("page.loadFailed")} />
      </Page>
    );
  }

  return (
    <Page>
      <header className="flex items-start gap-3">
        <img
          src="/agripulse-mark.png"
          alt="AgriPulse"
          className="h-12 w-12 shrink-0 object-contain"
        />
        <div>
          <PageHeader title={t("page.title")} />
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

      <SeasonContextBar farmId={farmId} />

      <FarmTrendChart farmId={farmId} />

      {/* One section for all of it: now → trend → outlook → risk. These were
          four sibling cards saying "weather" four times over the same data. */}
      {canReadWeather ? <WeatherSection farmId={farmId} showRisk={canReadRisk} /> : null}

      <BlockHealthScorecard farmId={farmId} />
    </Page>
  );
}
