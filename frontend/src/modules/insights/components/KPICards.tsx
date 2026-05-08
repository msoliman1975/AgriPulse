import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation("insights");

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
        title={t("kpi.landUnits.title")}
        value={blocksQuery.isLoading ? <Skeleton className="h-8 w-12" /> : totalBlocks}
        hint={t("kpi.landUnits.hint")}
      />
      <KPICard
        title={t("kpi.alerts.title")}
        value={
          alertsQuery.isLoading ? (
            <Skeleton className="h-8 w-12" />
          ) : (
            <span className={openAlertCount > 0 ? "text-ap-crit" : "text-ap-ink"}>
              {openAlertCount}
            </span>
          )
        }
        hint={
          openAlertCount === 0
            ? t("kpi.alerts.hintAllClear")
            : t("kpi.alerts.hintHasAlerts")
        }
        delta={
          openAlertCount > 0 ? (
            <Pill kind="crit">{t("kpi.alerts.deltaCrit")}</Pill>
          ) : (
            <Pill kind="ok">{t("kpi.alerts.deltaOk")}</Pill>
          )
        }
        onClick={() => navigate(`/alerts/${farmId}`)}
      />
      <KPICard
        title={t("kpi.recommendations.title")}
        value={
          recsQuery.isLoading ? <Skeleton className="h-8 w-12" /> : openRecCount
        }
        hint={
          openRecCount === 0
            ? t("kpi.recommendations.hintEmpty")
            : t("kpi.recommendations.hintHas")
        }
        onClick={() => navigate(`/recommendations/${farmId}`)}
      />
      <KPICard
        title={t("kpi.upcoming.title")}
        value={calendarQuery.isLoading ? <Skeleton className="h-8 w-12" /> : upcomingCount}
        hint={t("kpi.upcoming.hint")}
      />
      <KPICard
        title={t("kpi.irrigation.title")}
        value={irrigationQuery.isLoading ? <Skeleton className="h-8 w-12" /> : dueCount}
        hint={
          totalMm !== undefined && dueCount > 0
            ? t("kpi.irrigation.hintTotal", { mm: totalMm.toFixed(1) })
            : t("kpi.irrigation.hintEmpty")
        }
        onClick={() => navigate(`/plan/${farmId}`)}
      />
      <KPICard
        title={t("kpi.latestSignal.title")}
        value={
          signalsQuery.isLoading ? (
            <Skeleton className="h-8 w-12" />
          ) : latestSignalAt ? (
            renderRelativeShort(latestSignalAt, t)
          ) : (
            t("kpi.latestSignal.valueEmpty")
          )
        }
        hint={
          latestSignalAt
            ? t("kpi.latestSignal.hintHas")
            : t("kpi.latestSignal.hintEmpty")
        }
        onClick={() => navigate(`/signals/${farmId}`)}
      />
    </div>
  );
}

// `t` is the i18next TFunction; using `ReturnType` keeps the type
// branded with the "insights" namespace so TS still validates keys.
function renderRelativeShort(
  iso: string,
  t: ReturnType<typeof useTranslation<"insights">>["t"],
): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60000);
  if (min < 1) return t("kpi.latestSignal.justNow");
  if (min < 60) return t("kpi.latestSignal.minutesAgo", { n: min });
  const hr = Math.round(min / 60);
  if (hr < 24) return t("kpi.latestSignal.hoursAgo", { n: hr });
  const d = Math.round(hr / 24);
  return t("kpi.latestSignal.daysAgo", { n: d });
}
