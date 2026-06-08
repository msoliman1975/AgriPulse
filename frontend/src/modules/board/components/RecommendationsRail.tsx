import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listRecommendations, type Recommendation } from "@/api/recommendations";

interface RecommendationsRailProps {
  farmId: string;
  /**
   * Called by the cell's drop handler with the rec id. Implementation
   * lives in BoardPage so it can also drive the schedule API + cache
   * invalidation.
   */
  draggable: boolean;
}

/** Side rail listing open recs for the current farm. Each chip is
 * drag-source for drop-to-cell scheduling.
 */
export function RecommendationsRail({
  farmId,
  draggable,
}: RecommendationsRailProps): ReactNode {
  const { t } = useTranslation("board");
  const recsQ = useQuery<Recommendation[]>({
    queryKey: ["recommendations", "open", farmId],
    queryFn: () =>
      listRecommendations({ farm_id: farmId, state: "open", limit: 50 }),
    staleTime: 30_000,
  });

  return (
    <aside className="min-w-0 flex-[1]">
      <h2 className="px-2 pb-2 text-xs font-semibold uppercase tracking-wider text-ap-muted">
        {t("rail.title")}
      </h2>
      <div className="flex flex-col gap-1 rounded-xl border border-ap-line bg-ap-panel p-2">
        {recsQ.isLoading ? (
          <p className="px-2 py-3 text-xs text-ap-muted">…</p>
        ) : recsQ.isError ? (
          <p className="px-2 py-3 text-xs text-ap-crit">{t("rail.loadFailed")}</p>
        ) : (recsQ.data ?? []).length === 0 ? (
          <p className="px-2 py-3 text-xs text-ap-muted">{t("rail.empty")}</p>
        ) : (
          (recsQ.data ?? []).map((r) => (
            <RecChip key={r.id} rec={r} draggable={draggable} />
          ))
        )}
      </div>
    </aside>
  );
}

interface RecChipProps {
  rec: Recommendation;
  draggable: boolean;
}

function RecChip({ rec, draggable }: RecChipProps): ReactNode {
  const { t } = useTranslation("board");
  const severityColor =
    rec.severity === "critical"
      ? "border-ap-crit/30 bg-ap-crit-soft text-ap-crit"
      : rec.severity === "warning"
        ? "border-ap-warn/30 bg-ap-warn-soft text-ap-warn"
        : "border-sky-300 bg-sky-50 text-sky-900";
  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        // Carry the rec id + default activity_type so the cell drop
        // handler doesn't need to refetch the rec to do the schedule.
        e.dataTransfer.setData(
          "application/x-agripulse-rec",
          JSON.stringify({ id: rec.id, action_type: rec.action_type }),
        );
        e.dataTransfer.effectAllowed = "copy";
      }}
      className={
        "flex cursor-grab flex-col gap-0.5 rounded border px-2 py-1.5 text-xs " +
        severityColor
      }
      title={t("rail.dragHint")}
    >
      <span className="flex items-center justify-between">
        <span className="font-medium">{t(`recAction.${rec.action_type}`)}</span>
        <span className="text-[10px] uppercase text-ap-muted">
          {rec.severity}
        </span>
      </span>
      <span className="truncate text-[11px] opacity-90">{rec.text_en}</span>
    </div>
  );
}
