import { format, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Badge } from "@/components/Badge";
import { Skeleton } from "@/components/Skeleton";
import { useCalendar } from "@/queries/plans";
import { activityTypeLabel } from "@/rules/formatting";

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

export function UpcomingActivitiesCard({ farmId }: Props): ReactNode {
  const navigate = useNavigate();
  const { data, isLoading } = useCalendar(farmId, todayIso(), plusDaysIso(7));
  const activities = data?.activities ?? [];

  return (
    <section
      aria-labelledby="upcoming-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2
          id="upcoming-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          This week&apos;s activities
        </h2>
        <button
          type="button"
          onClick={() => navigate(`/plan/${farmId}`)}
          className="text-xs font-medium text-ap-primary hover:underline"
        >
          Plan →
        </button>
      </header>
      <div className="mt-3 flex flex-col gap-2">
        {isLoading ? (
          <>
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </>
        ) : activities.length === 0 ? (
          <p className="py-3 text-center text-sm text-ap-muted">
            Nothing scheduled this week.
          </p>
        ) : (
          activities.slice(0, 5).map((a) => {
            const d = parseISO(a.scheduled_date);
            return (
              <button
                type="button"
                key={a.id}
                onClick={() => navigate(`/plan/${farmId}?activity=${a.id}&lane=${a.block_id}`)}
                className="flex items-center gap-3 rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-start hover:bg-ap-line/30"
              >
                <div className="flex w-12 flex-none flex-col items-center text-ap-muted">
                  <span className="text-lg font-semibold leading-none text-ap-ink">
                    {format(d, "d")}
                  </span>
                  <span className="text-[10px] uppercase tracking-wider">{format(d, "EEE")}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-ap-ink">
                    {a.product_name ?? activityTypeLabel(a.activity_type)}
                  </div>
                  <div className="text-[11px] text-ap-muted">
                    {activityTypeLabel(a.activity_type)} · {a.duration_days}d
                    {a.start_time ? ` · ${a.start_time.slice(0, 5)}` : ""}
                  </div>
                </div>
                <Badge kind={`type-${a.activity_type === "irrigation" ? "irrig" : a.activity_type === "harvesting" ? "harv" : a.activity_type === "spraying" ? "spray" : a.activity_type === "fertilizing" ? "fert" : a.activity_type === "pruning" ? "prune" : a.activity_type === "planting" ? "plant" : a.activity_type}` as const}>
                  {a.activity_type.slice(0, 4)}
                </Badge>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
