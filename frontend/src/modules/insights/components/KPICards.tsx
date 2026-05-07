import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAlerts } from "@/queries/alerts";
import { useIrrigationSchedules } from "@/queries/irrigation";
import { useCalendar } from "@/queries/plans";
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

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
    </div>
  );
}
