import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listRecommendations, type Recommendation } from "@/api/recommendations";
import { Card } from "@/components/Card";

// A cell-scoped tree fires one rec per grid cell, so a single sweep can put
// dozens of near-identical "scout this zone" recs on the rail. Collapse the
// cell-scoped ones into a single summary chip per (tree, action, block); the
// block-scoped recs (one per block already) stay as individual drag chips.
type RailEntry =
  | { kind: "single"; rec: Recommendation }
  | { kind: "group"; key: string; recs: Recommendation[]; worst: Recommendation };

const SEVERITY_RANK: Record<string, number> = { info: 0, warning: 1, critical: 2 };

function buildRailEntries(recs: Recommendation[]): RailEntry[] {
  const singles: RailEntry[] = [];
  const groups = new Map<string, Recommendation[]>();
  for (const rec of recs) {
    if (rec.cell_id == null) {
      singles.push({ kind: "single", rec });
      continue;
    }
    const key = `${rec.tree_code}|${rec.action_type}|${rec.block_id}`;
    groups.set(key, [...(groups.get(key) ?? []), rec]);
  }
  const grouped: RailEntry[] = [...groups.entries()].map(([key, recs]) => {
    // A group of one is really a single — keep it draggable.
    if (recs.length === 1) return { kind: "single" as const, rec: recs[0] };
    const worst = recs.reduce((a, b) =>
      (SEVERITY_RANK[b.severity] ?? 0) > (SEVERITY_RANK[a.severity] ?? 0) ? b : a,
    );
    return { kind: "group" as const, key, recs, worst };
  });
  return [...singles, ...grouped];
}

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
export function RecommendationsRail({ farmId, draggable }: RecommendationsRailProps): ReactNode {
  const { t } = useTranslation("board");
  const recsQ = useQuery<Recommendation[]>({
    queryKey: ["recommendations", "open", farmId],
    queryFn: () => listRecommendations({ farm_id: farmId, state: "open", limit: 200 }),
    staleTime: 30_000,
  });
  const entries = useMemo(() => buildRailEntries(recsQ.data ?? []), [recsQ.data]);

  return (
    <aside className="min-w-0 flex-[1]">
      <h2 className="px-2 pb-2 text-xs font-semibold uppercase tracking-wider text-ap-muted">
        {t("rail.title")}
      </h2>
      <Card noPadding className="flex flex-col gap-1 p-2">
        {recsQ.isLoading ? (
          <p className="px-2 py-3 text-xs text-ap-muted">…</p>
        ) : recsQ.isError ? (
          <p className="px-2 py-3 text-xs text-ap-crit">{t("rail.loadFailed")}</p>
        ) : entries.length === 0 ? (
          <p className="px-2 py-3 text-xs text-ap-muted">{t("rail.empty")}</p>
        ) : (
          entries.map((entry) =>
            entry.kind === "single" ? (
              <RecChip key={entry.rec.id} rec={entry.rec} draggable={draggable} />
            ) : (
              <GroupChip key={entry.key} recs={entry.recs} worst={entry.worst} />
            ),
          )
        )}
      </Card>
    </aside>
  );
}

interface RecChipProps {
  rec: Recommendation;
  draggable: boolean;
}

function RecChip({ rec, draggable }: RecChipProps): ReactNode {
  const { t, i18n } = useTranslation("board");
  // Mirror the Recommendations page: prefer the decision-tree's localized
  // Arabic text, falling back to English when it wasn't authored.
  const isAr = i18n.language === "ar";
  const localizedText = isAr ? (rec.text_ar ?? rec.text_en) : rec.text_en;
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
        "flex cursor-grab flex-col gap-0.5 rounded border px-2 py-1.5 text-xs " + severityColor
      }
      title={t("rail.dragHint")}
    >
      <span className="flex items-center justify-between">
        <span className="font-medium">{t(`recAction.${rec.action_type}`)}</span>
        <span className="text-[10px] uppercase text-ap-muted">{t(`severity.${rec.severity}`)}</span>
      </span>
      <span className="truncate text-[11px] opacity-90">{localizedText}</span>
    </div>
  );
}

// Summary chip for a set of cell-scoped recs (one tree/action, many zones).
// Not draggable — dropping a whole zone-set onto one calendar cell is
// ambiguous; the author acts on individual zones from the map / recs page.
function GroupChip({ recs, worst }: { recs: Recommendation[]; worst: Recommendation }): ReactNode {
  const { t } = useTranslation("board");
  const severityColor =
    worst.severity === "critical"
      ? "border-ap-crit/30 bg-ap-crit-soft text-ap-crit"
      : worst.severity === "warning"
        ? "border-ap-warn/30 bg-ap-warn-soft text-ap-warn"
        : "border-sky-300 bg-sky-50 text-sky-900";
  return (
    <div
      className={"flex flex-col gap-0.5 rounded border px-2 py-1.5 text-xs " + severityColor}
      title={t("rail.zonesHint")}
    >
      <span className="flex items-center justify-between">
        <span className="font-medium">{t(`recAction.${worst.action_type}`)}</span>
        <span className="rounded-full bg-black/5 px-1.5 text-[10px] font-medium">
          {t("rail.zonesCount", { count: recs.length })}
        </span>
      </span>
      <span className="truncate text-[11px] opacity-90">{worst.text_en}</span>
    </div>
  );
}
