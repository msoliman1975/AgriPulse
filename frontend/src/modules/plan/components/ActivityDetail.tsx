import { format, parseISO } from "date-fns";
import type { ReactNode } from "react";

import type { Block } from "@/api/blocks";
import type { IrrigationSchedule } from "@/api/irrigation";
import type { PlanActivity } from "@/api/plans";
import { Badge } from "@/components/Badge";
import { Pill } from "@/components/Pill";
import { useApplyOrSkipIrrigation } from "@/queries/irrigation";
import { useUpdateActivity } from "@/queries/plans";
import { activityTypeLabel } from "@/rules/formatting";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  farmId: string;
  activity: PlanActivity | null;
  block: Block | null;
  /** When the selected bar is an irrigation projection, the source row. */
  irrigation: IrrigationSchedule | null;
}

export function ActivityDetail({ farmId, activity, block, irrigation }: Props): ReactNode {
  const canComplete = useCapability("plan_activity.complete", { farmId });
  const canManageIrrigation = useCapability("irrigation.schedule.manage", { farmId });
  const updateActivity = useUpdateActivity();
  const transitionIrrigation = useApplyOrSkipIrrigation();

  if (!activity) {
    return (
      <aside className="w-80 flex-none overflow-y-auto border-s border-ap-line bg-ap-panel p-4">
        <p className="py-12 text-center text-sm text-ap-muted">
          Select an activity bar to see details, conflicts &amp; actions.
        </p>
      </aside>
    );
  }

  const isIrrigation = irrigation !== null;
  return (
    <aside className="flex w-80 flex-none flex-col overflow-y-auto border-s border-ap-line bg-ap-panel">
      <header className="border-b border-ap-line p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            kind={
              `type-${activity.activity_type === "irrigation" ? "irrig" : activity.activity_type === "harvesting" ? "harv" : activity.activity_type === "spraying" ? "spray" : activity.activity_type === "fertilizing" ? "fert" : activity.activity_type === "pruning" ? "prune" : activity.activity_type === "planting" ? "plant" : activity.activity_type}` as const
            }
          >
            {activityTypeLabel(activity.activity_type)}
          </Badge>
          <Pill
            kind={
              activity.status === "completed"
                ? "ok"
                : activity.status === "skipped"
                  ? "neutral"
                  : "info"
            }
          >
            {activity.status}
          </Pill>
        </div>
        <h2 className="mt-2 text-base font-semibold text-ap-ink">
          {activity.product_name ?? activityTypeLabel(activity.activity_type)} —{" "}
          {block?.name ?? block?.code ?? "—"}
        </h2>
        <p className="mt-1 text-xs text-ap-muted">
          {format(parseISO(activity.scheduled_date), "EEEE, MMMM d")}
          {activity.start_time ? ` · ${activity.start_time.slice(0, 5)}` : ""}
        </p>
      </header>

      <section className="border-b border-ap-line p-4">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
          Activity
        </h3>
        <dl className="grid grid-cols-3 gap-x-2 gap-y-1 text-sm">
          <Row label="Type" value={activityTypeLabel(activity.activity_type)} />
          <Row label="Product" value={activity.product_name ?? "—"} />
          <Row label="Dosage" value={activity.dosage ?? "—"} />
          <Row label="Duration" value={`${activity.duration_days}d`} />
          <Row label="Start time" value={activity.start_time?.slice(0, 5) ?? "—"} />
          <Row label="Status" value={activity.status} />
        </dl>
      </section>

      {isIrrigation && irrigation ? (
        <section className="border-b border-ap-line p-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
            Irrigation recommendation
          </h3>
          <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-sm">
            <Row label="Recommended" value={`${irrigation.recommended_mm} mm`} />
            <Row label="ET₀" value={irrigation.et0_mm_used ?? "—"} />
            <Row label="Kc" value={irrigation.kc_used ?? "—"} />
            <Row label="Recent precip" value={irrigation.recent_precip_mm ?? "—"} />
            <Row label="Stage" value={irrigation.growth_stage_context ?? "—"} />
          </dl>
        </section>
      ) : null}

      {activity.notes ? (
        <section className="border-b border-ap-line p-4 text-sm text-ap-ink">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
            Notes
          </h3>
          {activity.notes}
        </section>
      ) : null}

      <div className="mt-auto flex flex-col gap-2 border-t border-ap-line p-4">
        {isIrrigation && irrigation ? (
          <>
            <button
              type="button"
              disabled={!canManageIrrigation || irrigation.status !== "pending"}
              onClick={() =>
                transitionIrrigation.mutate({
                  scheduleId: irrigation.id,
                  payload: {
                    action: "apply",
                    applied_volume_mm: Number(irrigation.recommended_mm),
                  },
                })
              }
              className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Apply ({irrigation.recommended_mm} mm)
            </button>
            <button
              type="button"
              disabled={!canManageIrrigation || irrigation.status !== "pending"}
              onClick={() =>
                transitionIrrigation.mutate({
                  scheduleId: irrigation.id,
                  payload: { action: "skip" },
                })
              }
              className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-50"
            >
              Skip
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={
                !canComplete || activity.status === "completed" || activity.status === "skipped"
              }
              onClick={() =>
                updateActivity.mutate({
                  activityId: activity.id,
                  payload: { state: "complete" },
                })
              }
              className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Mark complete
            </button>
            <button
              type="button"
              disabled={
                !canComplete || activity.status === "completed" || activity.status === "skipped"
              }
              onClick={() =>
                updateActivity.mutate({
                  activityId: activity.id,
                  payload: { state: "skip" },
                })
              }
              className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-50"
            >
              Skip
            </button>
          </>
        )}
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <>
      <dt className="col-span-1 text-[11px] uppercase tracking-wider text-ap-muted">{label}</dt>
      <dd className="col-span-2 truncate text-ap-ink">{value}</dd>
    </>
  );
}
