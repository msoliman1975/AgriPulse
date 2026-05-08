import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";

import { useEffect, useState } from "react";

import { getFarm } from "@/api/farms";
import { listBlocks, type Block } from "@/api/blocks";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { WeatherForecastPanel } from "@/modules/weather/components/WeatherForecastPanel";
import { AlertsFeedCard } from "../components/AlertsFeedCard";
import { KPICards } from "../components/KPICards";
import { LandUnitHealthTable } from "../components/LandUnitHealthTable";
import { LatestSignalsCard } from "../components/LatestSignalsCard";
import { TrendChartCard } from "../components/TrendChartCard";
import { UpcomingActivitiesCard } from "../components/UpcomingActivitiesCard";

export function InsightsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const navigate = useNavigate();
  const { t } = useTranslation("insights");
  const dateLocale = useDateLocale();
  const { data: farm, isLoading } = useQuery({
    queryKey: ["farms", "detail", farmId] as const,
    queryFn: () => getFarm(farmId!),
    enabled: Boolean(farmId),
  });
  const canReadWeather = useCapability("weather.read", { farmId });

  // Pull the farm's first block so we can mount the WeatherForecastPanel,
  // which keys on block_id but resolves to the farm's centroid internally.
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

  const greeting = t(`greeting.${greetingKeyForHour(new Date().getHours())}`);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-start gap-3">
          <img
            src="/agripulse-mark.png"
            alt="Agri.Pulse"
            className="h-12 w-12 shrink-0 object-contain"
          />
          <div>
            <h1 className="text-2xl font-semibold text-ap-ink">
              {greeting}.
            </h1>
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
        </div>
        <button
          type="button"
          onClick={() => navigate(`/plan/${farmId}`)}
          className="inline-flex items-center gap-1 rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          {t("page.newPlan")}
        </button>
      </header>

      <KPICards farmId={farmId} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <TrendChartCard farmId={farmId} />
          {canReadWeather && firstBlock ? (
            <WeatherForecastPanel
              blockId={firstBlock.id}
              farmId={farmId}
              farmName={farm?.name ?? null}
            />
          ) : null}
          <LandUnitHealthTable farmId={farmId} />
        </div>
        <div className="flex flex-col gap-4">
          <AlertsFeedCard farmId={farmId} />
          <LatestSignalsCard farmId={farmId} />
          <UpcomingActivitiesCard farmId={farmId} />
        </div>
      </div>
    </div>
  );
}

function greetingKeyForHour(hour: number): "morning" | "afternoon" | "evening" {
  if (hour < 5) return "evening";
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}
