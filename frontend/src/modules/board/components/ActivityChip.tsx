import clsx from "clsx";
import { format, parseISO } from "date-fns";
import type { MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType, BoardActivity } from "@/api/plans";

/** Color hint per activity type. Keep keys aligned with backend ActivityType. */
const TYPE_TINT: Record<ActivityType, string> = {
  planting: "bg-emerald-50 text-emerald-900 border-emerald-200",
  fertilizing: "bg-amber-50 text-amber-900 border-amber-200",
  spraying: "bg-rose-50 text-rose-900 border-rose-200",
  pruning: "bg-purple-50 text-purple-900 border-purple-200",
  harvesting: "bg-orange-50 text-orange-900 border-orange-200",
  irrigation: "bg-sky-50 text-sky-900 border-sky-200",
  soil_prep: "bg-stone-50 text-stone-900 border-stone-200",
  observation: "bg-slate-50 text-slate-900 border-slate-200",
};

const TYPE_ICON: Record<ActivityType, string> = {
  planting: "🌱",
  fertilizing: "🧪",
  spraying: "💨",
  pruning: "✂️",
  harvesting: "🌾",
  irrigation: "💧",
  soil_prep: "⛏",
  observation: "👁",
};

interface ActivityChipProps {
  activity: BoardActivity;
  onClick: (e: MouseEvent<HTMLButtonElement>) => void;
}

export function ActivityChip({ activity, onClick }: ActivityChipProps): ReactNode {
  const { t } = useTranslation("board");
  const tint = TYPE_TINT[activity.activity_type] ?? "bg-ap-bg text-ap-ink border-ap-line";
  const icon = TYPE_ICON[activity.activity_type] ?? "•";
  const dayLabel = format(parseISO(activity.scheduled_date), "EEE");
  const isCompleted = activity.status === "completed";
  const isSkipped = activity.status === "skipped";

  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "flex flex-col gap-0.5 rounded border px-2 py-1 text-left text-xs transition-colors",
        tint,
        isCompleted && "opacity-60 line-through",
        isSkipped && "opacity-40 line-through",
      )}
      title={`${t(`type.${activity.activity_type}`)} — ${activity.scheduled_date}`}
    >
      <span className="flex items-center gap-1 font-medium">
        <span aria-hidden="true">{icon}</span>
        <span className="truncate">{t(`type.${activity.activity_type}`)}</span>
        <span className="ms-auto text-[10px] uppercase text-ap-muted">{dayLabel}</span>
      </span>
      {activity.resources.length > 0 ? (
        <span className="truncate text-[11px] text-ap-muted">
          {activity.resources
            .slice(0, 2)
            .map((r) => `${r.kind === "worker" ? "👤" : "🔧"} ${r.name}`)
            .join(" · ")}
          {activity.resources.length > 2
            ? ` +${activity.resources.length - 2}`
            : ""}
        </span>
      ) : null}
    </button>
  );
}
