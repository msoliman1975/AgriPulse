import clsx from "clsx";
import { format, parseISO } from "date-fns";
import type { MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType, BoardActivity } from "@/api/plans";

/** Color hint per activity type, using the design system's ap activity tokens
 *  (soft wash + token text + soft border). Keep keys aligned with backend
 *  ActivityType. soil_prep / observation have no dedicated token, so they use
 *  the neutral surface and the accent respectively. */
const TYPE_TINT: Record<ActivityType, string> = {
  planting: "bg-ap-plant/10 text-ap-plant border-ap-plant/30",
  fertilizing: "bg-ap-fert/10 text-ap-fert border-ap-fert/30",
  spraying: "bg-ap-spray/10 text-ap-spray border-ap-spray/30",
  pruning: "bg-ap-prune/10 text-ap-prune border-ap-prune/30",
  harvesting: "bg-ap-harv/10 text-ap-harv border-ap-harv/30",
  irrigation: "bg-ap-irrig/10 text-ap-irrig border-ap-irrig/30",
  soil_prep: "bg-ap-bg text-ap-ink border-ap-line",
  observation: "bg-ap-accent/10 text-ap-accent border-ap-accent/30",
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
