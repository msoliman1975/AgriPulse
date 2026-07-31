// "Conditions" tab of the Block Dock — why each decision tree did or didn't
// fire on this block. Reads the read-only explain endpoint, which re-walks
// the trees without writing anything, so trees that came out clear (and so
// leave no recommendation row behind) are visible here too.
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { explainBlock, type ExplainStep, type ExplainTree } from "@/api/recommendations";
import { localizedField } from "@/lib/localizedField";
import { HEALTH_DOT } from "./constants";
import { decisionSteps, failingCount, leafStep, readCondition } from "./dockFormat";
import { Dot } from "./ui";

function statusColor(tree: ExplainTree): string {
  if (tree.status === "fired") return HEALTH_DOT.critical;
  if (tree.status === "clear") return HEALTH_DOT.healthy;
  return HEALTH_DOT.unknown;
}

function StepRow({ step, fired }: { step: ExplainStep; fired: boolean }): ReactNode {
  const { i18n } = useTranslation("farmConsole");
  const reading = readCondition(step);
  const label =
    localizedField(i18n.language, step.label_en, step.label_ar) ?? step.node_id;
  // A condition evaluating false is NOT a failure — it just means the walk
  // took the other branch. Only mark it red when the tree actually fired, so
  // a block with nothing wrong doesn't read as a wall of red crosses.
  const mark = step.matched ? "✓" : fired ? "✕" : "○";
  const color = step.matched
    ? HEALTH_DOT.healthy
    : fired
      ? HEALTH_DOT.critical
      : HEALTH_DOT.unknown;
  return (
    <div className="flex items-start gap-2 border-b border-ap-line/70 py-1.5 last:border-b-0">
      <span aria-hidden="true" className="mt-px w-3.5 text-center text-xs font-bold" style={{ color }}>
        {mark}
      </span>
      <span className="min-w-0 flex-1 text-sm text-ap-ink">{label}</span>
      <span className="whitespace-nowrap text-xs tabular-nums text-ap-muted">
        {reading.actual ?? "—"}
        {reading.threshold ? <span className="opacity-70"> · {reading.threshold}</span> : null}
      </span>
    </div>
  );
}

export function DockConditionsView({
  blockId,
  farmId,
  onFailingCountChange,
}: {
  blockId: string;
  farmId: string;
  onFailingCountChange?: (n: number | null) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null);

  const explainQ = useQuery({
    queryKey: ["labs/mapnext/explain", blockId, farmId],
    queryFn: () => explainBlock(blockId, farmId),
    staleTime: 60_000,
  });

  const trees = explainQ.data?.trees ?? [];
  // Trees that actually ran here. Targeting-skipped ones are summarised in a
  // footer instead — listing 40 mango trees on a citrus block is noise.
  const ran = trees.filter((tr) => tr.status !== "skipped");
  const skipped = trees.length - ran.length;

  // The tab badge counts unmet checks on trees that actually FIRED. Counting
  // them on clear trees turned "nothing is wrong here" into a red badge.
  const totalFailing = ran
    .filter((tr) => tr.status === "fired")
    .reduce((n, tr) => n + failingCount(tr.steps), 0);
  useEffect(() => {
    onFailingCountChange?.(explainQ.data ? totalFailing : null);
  }, [onFailingCountChange, explainQ.data, totalFailing]);

  useEffect(() => {
    setSelectedTreeId(null);
  }, [blockId]);

  if (explainQ.isLoading) {
    return (
      <div className="grid h-full grid-cols-[236px_minmax(0,1fr)] gap-6">
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-9 animate-pulse rounded-lg bg-ap-line/50" />
          ))}
        </div>
        <div className="h-32 animate-pulse rounded-xl bg-ap-line/40" />
      </div>
    );
  }

  if (explainQ.isError) {
    return <div className="text-sm text-ap-muted">{t("dock.conditions.error")}</div>;
  }

  if (!ran.length) {
    return (
      <div className="max-w-lg text-sm text-ap-muted">
        {skipped
          ? t("dock.conditions.noneTargeted", { count: skipped })
          : t("dock.conditions.noneAtAll")}
      </div>
    );
  }

  const active = ran.find((tr) => tr.tree_id === selectedTreeId) ?? ran[0];
  const checks = decisionSteps(active.steps);
  const leaf = leafStep(active.steps);
  const verdict =
    localizedField(i18n.language, active.text_en, active.text_ar) ??
    localizedField(i18n.language, leaf?.label_en ?? null, leaf?.label_ar ?? null) ??
    (active.status === "clear" ? t("dock.conditions.noAction") : null);

  return (
    <div className="grid h-full grid-cols-[236px_minmax(0,1fr)] gap-6">
      {/* tree list */}
      <div className="min-h-0 overflow-auto pe-1">
        <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("dock.conditions.treesHeading")}
        </div>
        <div className="space-y-1">
          {ran.map((tr) => {
            const failing = failingCount(tr.steps);
            const name = localizedField(i18n.language, tr.name_en, tr.name_ar) ?? tr.code;
            return (
              <button
                key={tr.tree_id}
                type="button"
                aria-pressed={tr.tree_id === active.tree_id}
                onClick={() => setSelectedTreeId(tr.tree_id)}
                className={clsx(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-start text-sm",
                  tr.tree_id === active.tree_id
                    ? "bg-ap-primary-soft font-semibold text-ap-ink"
                    : "text-ap-ink hover:bg-ap-bg/60",
                )}
              >
                <Dot color={statusColor(tr)} />
                <span className="min-w-0 flex-1 truncate">{name}</span>
                <span className="whitespace-nowrap text-xs text-ap-muted">
                  {tr.status === "per_cell"
                    ? t("dock.conditions.perCellShort")
                    : tr.status === "fired" && failing
                      ? t("dock.conditions.nFailing", { count: failing })
                      : tr.status === "fired"
                        ? t("dock.conditions.action")
                        : t("inspector.clear")}
                </span>
              </button>
            );
          })}
        </div>
        {skipped ? (
          <div className="mt-2 px-2.5 text-xs text-ap-muted">
            {t("dock.conditions.nSkipped", { count: skipped })}
          </div>
        ) : null}
      </div>

      {/* checks for the selected tree */}
      <div className="min-h-0 overflow-auto">
        <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-ap-primary">
          {localizedField(i18n.language, active.name_en, active.name_ar) ?? active.code}
        </div>

        {active.status === "per_cell" ? (
          <p className="max-w-lg text-sm text-ap-muted">{t("dock.conditions.perCell")}</p>
        ) : active.status === "error" ? (
          <p className="max-w-lg text-sm text-ap-crit">
            {t("dock.conditions.treeError", { error: active.error ?? "" })}
          </p>
        ) : checks.length ? (
          <>
            <div className="rounded-xl border border-ap-line px-3 py-1">
              {checks.map((s) => (
                <StepRow key={s.node_id} step={s} fired={active.status === "fired"} />
              ))}
            </div>
            {verdict ? (
              <p className="mt-2.5 text-sm text-ap-ink">
                <span className="text-ap-muted">{t("dock.conditions.outcome")} </span>
                {verdict}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-ap-muted">{t("dock.conditions.noChecks")}</p>
        )}
      </div>
    </div>
  );
}
