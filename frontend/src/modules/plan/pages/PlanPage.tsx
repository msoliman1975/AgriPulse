import { useQuery } from "@tanstack/react-query";
import { addMonths, startOfMonth } from "date-fns";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { listBlocks } from "@/api/blocks";
import type { IrrigationSchedule } from "@/api/irrigation";
import type { PlanActivity } from "@/api/plans";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useUrlSelection } from "@/hooks/useUrlSelection";
import { useCapability } from "@/rbac/useCapability";
import { useIrrigationSchedules } from "@/queries/irrigation";
import { useActivities, useCreatePlan, usePlans } from "@/queries/plans";
import { detectConflicts } from "@/rules/conflicts";
import { usePlanFilters } from "@/state/planFilters";
import { usePlanSelection } from "@/state/planSelection";

import { ActivityDetail } from "../components/ActivityDetail";
import { LaneSidebar } from "../components/LaneSidebar";
import { NewActivityModal } from "../components/NewActivityModal";
import { PlanToolbar } from "../components/PlanToolbar";
import { Timeline } from "../components/Timeline";

export function PlanPage(): ReactNode {
  const farmId = useActiveFarmId();
  useUrlSelection();
  const { activityId, clear } = usePlanSelection();
  const { activeTypes, draftsOnly } = usePlanFilters();

  // Esc clears selection.
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Escape") clear();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [clear]);

  const blocksQuery = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId!),
    enabled: Boolean(farmId),
  });
  const blocks = useMemo(() => blocksQuery.data?.items ?? [], [blocksQuery.data]);
  const blockById = useMemo(() => new Map(blocks.map((b) => [b.id, b])), [blocks]);

  // Pick the active plan (prefer one with status=active, fallback first).
  const plansQuery = usePlans(farmId);
  const activePlan = useMemo(() => {
    const list = plansQuery.data ?? [];
    return list.find((p) => p.status === "active") ?? list[0];
  }, [plansQuery.data]);

  const activitiesQuery = useActivities(activePlan?.id);
  const realActivities: PlanActivity[] = useMemo(
    () => activitiesQuery.data ?? [],
    [activitiesQuery.data],
  );

  // Season window: pick the year of the active plan, fallback to current year.
  const { seasonStart, seasonEnd } = useMemo(() => {
    const year = activePlan?.season_year ?? new Date().getFullYear();
    const start = new Date(year, 2, 1); // Mar 1
    const end = startOfMonth(addMonths(start, 8)); // Mar..Oct
    return { seasonStart: start, seasonEnd: end };
  }, [activePlan?.season_year]);

  // Irrigation projection: pull pending/applied schedules for the season
  // window, project each as a synthetic PlanActivity with type=irrigation.
  const seasonFromIso = seasonStart.toISOString().slice(0, 10);
  const seasonToIso = seasonEnd.toISOString().slice(0, 10);
  const irrigationQuery = useIrrigationSchedules(farmId, {
    from: seasonFromIso,
    to: seasonToIso,
  });
  const irrigationRows: IrrigationSchedule[] = useMemo(
    () => irrigationQuery.data ?? [],
    [irrigationQuery.data],
  );
  const projectedActivities: PlanActivity[] = useMemo(
    () =>
      irrigationRows.map((s) => ({
        id: `irrig-${s.id}`,
        plan_id: activePlan?.id ?? "irrig",
        block_id: s.block_id,
        activity_type: "irrigation",
        scheduled_date: s.scheduled_for,
        duration_days: 1,
        start_time: null,
        product_name: `${s.recommended_mm} mm`,
        dosage: null,
        notes: s.growth_stage_context,
        status:
          s.status === "applied" ? "completed" : s.status === "skipped" ? "skipped" : "scheduled",
        completed_at: s.applied_at,
        completed_by: s.applied_by,
        created_at: s.created_at,
        updated_at: s.updated_at,
      })),
    [irrigationRows, activePlan?.id],
  );

  const allActivities = useMemo(
    () => [...realActivities, ...projectedActivities],
    [realActivities, projectedActivities],
  );

  const conflicts = useMemo(() => detectConflicts(allActivities), [allActivities]);

  const visibleActivities = useMemo(
    () =>
      allActivities.filter(
        (a) => activeTypes.has(a.activity_type) && (!draftsOnly || a.status === "scheduled"),
      ),
    [allActivities, activeTypes, draftsOnly],
  );

  const totals = useMemo(() => {
    const completed = visibleActivities.filter((a) => a.status === "completed").length;
    const upcoming = visibleActivities.filter((a) => a.status === "scheduled").length;
    return {
      all: allActivities.length,
      visible: visibleActivities.length,
      completed,
      atRisk: conflicts.length,
      upcoming,
    };
  }, [allActivities.length, visibleActivities, conflicts.length]);

  const selectedActivity = useMemo(() => {
    if (!activityId) return null;
    if (activityId.startsWith("irrig-")) {
      return projectedActivities.find((a) => a.id === activityId) ?? null;
    }
    return realActivities.find((a) => a.id === activityId) ?? null;
  }, [activityId, projectedActivities, realActivities]);

  const selectedIrrigation = useMemo<IrrigationSchedule | null>(() => {
    if (!activityId?.startsWith("irrig-")) return null;
    const id = activityId.slice("irrig-".length);
    return irrigationRows.find((r) => r.id === id) ?? null;
  }, [activityId, irrigationRows]);

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return <PlanPageInner
    farmId={farmId}
    blocks={blocks}
    blocksLoading={blocksQuery.isLoading}
    realActivities={realActivities}
    visibleActivities={visibleActivities}
    conflicts={conflicts}
    seasonStart={seasonStart}
    seasonEnd={seasonEnd}
    blockById={blockById}
    selectedActivity={selectedActivity}
    selectedIrrigation={selectedIrrigation}
    activePlan={activePlan ?? null}
    totals={totals}
  />;
}

interface PlanPageInnerProps {
  farmId: string;
  blocks: ReturnType<typeof listBlocks> extends Promise<infer T> ? T extends { items: (infer B)[] } ? B[] : never : never;
  blocksLoading: boolean;
  realActivities: PlanActivity[];
  visibleActivities: PlanActivity[];
  conflicts: ReturnType<typeof detectConflicts>;
  seasonStart: Date;
  seasonEnd: Date;
  blockById: Map<string, PlanPageInnerProps["blocks"][number]>;
  selectedActivity: PlanActivity | null;
  selectedIrrigation: IrrigationSchedule | null;
  activePlan: import("@/api/plans").Plan | null;
  totals: { all: number; visible: number; completed: number; atRisk: number; upcoming: number };
}

function PlanPageInner(props: PlanPageInnerProps): ReactNode {
  const {
    farmId,
    blocks,
    blocksLoading,
    realActivities,
    visibleActivities,
    conflicts,
    seasonStart,
    seasonEnd,
    blockById,
    selectedActivity,
    selectedIrrigation,
    activePlan,
    totals,
  } = props;

  const [newOpen, setNewOpen] = useState(false);
  const canManagePlan = useCapability("plan.manage", { farmId });
  const createPlan = useCreatePlan();

  const handleCreatePlan = async (): Promise<void> => {
    if (!canManagePlan) return;
    const year = new Date().getFullYear();
    await createPlan.mutateAsync({
      farmId,
      payload: {
        season_label: `${year}-default`,
        season_year: year,
        name: `Season ${year}`,
      },
    });
  };

  return (
    <div className="-mx-4 -my-6 flex flex-col">
      <div className="flex items-center gap-2 border-b border-ap-line bg-ap-panel px-4 py-2">
        <h1 className="text-sm font-semibold text-ap-ink">
          {activePlan?.name ?? activePlan?.season_label ?? "No active plan"}
        </h1>
        <span className="ms-auto" />
        {!activePlan ? (
          <button
            type="button"
            disabled={!canManagePlan || createPlan.isPending}
            onClick={handleCreatePlan}
            className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-50"
          >
            {createPlan.isPending ? "Creating…" : "+ Create season plan"}
          </button>
        ) : (
          <button
            type="button"
            disabled={!canManagePlan}
            onClick={() => setNewOpen(true)}
            className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-50"
          >
            + New activity
          </button>
        )}
      </div>
      <PlanToolbar totals={totals} />
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: "calc(100vh - 220px)" }}>
        <LaneSidebar blocks={blocks} isLoading={blocksLoading} />
        <Timeline
          blocks={blocks}
          activities={visibleActivities}
          conflicts={conflicts}
          seasonStart={seasonStart}
          seasonEnd={seasonEnd}
        />
        <ActivityDetail
          farmId={farmId}
          activity={selectedActivity}
          block={selectedActivity ? (blockById.get(selectedActivity.block_id) ?? null) : null}
          irrigation={selectedIrrigation}
        />
      </div>
      <NewActivityModal
        open={newOpen}
        onClose={() => setNewOpen(false)}
        farmId={farmId}
        plan={activePlan}
        blocks={blocks}
        existingActivities={realActivities}
      />
    </div>
  );
}
