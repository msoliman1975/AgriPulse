import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAlerts } from "@/queries/alerts";
import { useIrrigationSchedules } from "@/queries/irrigation";
import { useCalendar } from "@/queries/plans";
import { useRecommendations } from "@/queries/recommendations";
import { useSignalObservations } from "@/queries/signals";
import { KPICard } from "@/components/KPICard";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useQuery } from "@tanstack/react-query";
import { listBlocks } from "@/api/blocks";

interface Props {
  farmId: string;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function plusDaysIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function KPICards({ farmId }: Props): ReactNode {
  const navigate = useNavigate();

  const blocksQuery = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId),
    enabled: Boolean(farmId),
  });
  const totalBlocks = blocksQuery.data?.items.length ?? 0;

  const alertsQuery = useAlerts({ status: "open" });
  const openAlertCount = alertsQuery.data?.length ?? 0;

  const today = todayIso();
  const weekOut = plusDaysIso(7);
  const irrigationQuery = useIrrigationSchedules(farmId, {
    status: ["pending"],
    from: today,
    to: weekOut,
  });
  const dueCount = irrigationQuery.data?.length ?? 0;
  const totalMm = irrigationQuery.data?.reduce(
    (acc, r) => acc + Number(r.recommended_mm ?? 0),
    0,
  );

  const calendarQuery = useCalendar(farmId, today, weekOut);
  const upcomingCount = calendarQuery.data?.activities.length ?? 0;

  const recsQuery = useRecommendations({ farm_id: farmId, state: "open" });
  const openRecCount = recsQuery.data?.length ?? 0;

  const signalsQuery = useSignalObservations({ farm_id: farmId, limit: 1 });
  const latestSignalAt = signalsQuery.data?.[0]?.time;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      <KPICard
        title="Land units"
        value={blocksQuery.isLoading ? <Skeleton className="h-8 w-12" /> : totalBlocks}
        hint="Active blocks in this farm"
      />
      <KPICard
        title="Active alerts"
        value={
          alertsQuery.isLoading ? (
            <Skeleton className="h-8 w-12" />
          ) : (
            <span className={openAlertCount > 0 ? "text-ap-crit" : "text-ap-ink"}>
              {openAlertCount}
            </span>
          )
        }
        hint={openAlertCount === 0 ? "All clear" : "Sorted by severity"}
        delta={
          openAlertCount > 0 ? (
            <Pill kind="crit">needs attention</Pill>
          ) : (
            <Pill kind="ok">healthy</Pill>
          )
        }
        onClick={() => navigate(`/alerts/${farmId}`)}
      />
      <KPICard
        title="Open recommendations"
        value={
          recsQuery.isLoading ? <Skeleton className="h-8 w-12" /> : openRecCount
        }
        hint={openRecCount === 0 ? "Nothing pending" : "Apply, dismiss, or defer"}
        onClick={() => navigate(`/recommendations/${farmId}`)}
      />
      <KPICard
        title="Upcoming activities"
        value={calendarQuery.isLoading ? <Skeleton className="h-8 w-12" /> : upcomingCount}
        hint="Next 7 days, across all plans"
      />
      <KPICard
        title="Irrigation due"
        value={irrigationQuery.isLoading ? <Skeleton className="h-8 w-12" /> : dueCount}
        hint={
          totalMm !== undefined && dueCount > 0
            ? `${totalMm.toFixed(1)} mm total recommended`
            : "Pending recommendations"
        }
        onClick={() => navigate(`/plan/${farmId}`)}
      />
      <KPICard
        title="Latest signal"
        value={
          signalsQuery.isLoading ? (
            <Skeleton className="h-8 w-12" />
          ) : latestSignalAt ? (
            relativeShort(latestSignalAt)
          ) : (
            "—"
          )
        }
        hint={latestSignalAt ? "Most recent observation" : "No observations yet"}
        onClick={() => navigate(`/signals/${farmId}`)}
      />
    </div>
  );
}

function relativeShort(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  return `${d}d ago`;
}
