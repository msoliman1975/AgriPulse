import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import type { ReactNode } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { getFarm } from "@/api/farms";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { AlertsFeedCard } from "../components/AlertsFeedCard";
import { KPICards } from "../components/KPICards";
import { LandUnitHealthTable } from "../components/LandUnitHealthTable";
import { TrendChartCard } from "../components/TrendChartCard";
import { UpcomingActivitiesCard } from "../components/UpcomingActivitiesCard";

export function InsightsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const navigate = useNavigate();
  const { data: farm, isLoading } = useQuery({
    queryKey: ["farms", "detail", farmId] as const,
    queryFn: () => getFarm(farmId!),
    enabled: Boolean(farmId),
  });

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  const greeting = greetingForHour(new Date().getHours());

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">
            {greeting}.
          </h1>
          <p className="mt-1 text-sm text-ap-muted">
            {isLoading ? (
              <Skeleton className="inline-block h-4 w-64" />
            ) : (
              <>
                <span className="font-medium text-ap-ink">{farm?.name ?? "—"}</span>
                {farm ? (
                  <>
                    {" · "}
                    {(farm.area_value ?? 0).toFixed(1)} {farm.area_unit}
                    {" · "}
                    {format(new Date(), "EEEE, MMMM d")}
                  </>
                ) : null}
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate(`/plan/${farmId}`)}
          className="inline-flex items-center gap-1 rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          + New plan
        </button>
      </header>

      <KPICards farmId={farmId} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <TrendChartCard farmId={farmId} />
          <LandUnitHealthTable farmId={farmId} />
        </div>
        <div className="flex flex-col gap-4">
          <AlertsFeedCard farmId={farmId} />
          <UpcomingActivitiesCard farmId={farmId} />
        </div>
      </div>
    </div>
  );
}

function greetingForHour(hour: number): string {
  if (hour < 5) return "Good evening";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
