// Set and see a block's phenological stage.
//
// The stage is the most-used gate in the decision-tree catalogue — seven
// published trees branch on it — and until now nothing in the product could
// set it. A daily task advances it from the crop's stage calendar, which is
// right most of the time and wrong exactly when a season runs early or late,
// which is when the advice matters most.
//
// Two things make this more than a dropdown:
//
//   * A transition is an EVENT, not a field edit. Recording one appends to the
//     block's phenology timeline with who said so, so "why did this block get
//     flowering advice in March" stays answerable.
//   * Setting a stage by hand is pointless if the nightly sweep overwrites it,
//     so the lock rides alongside rather than hiding in another screen.
//
// The empty state carries real weight: most crops have no stage calendar at
// all, and a block whose crop has none can never advance on its own. Saying so
// here is the only place an agronomist would find out.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getResolvedTaxonomy } from "@/api/crops";
import {
  listGrowthStages,
  recordGrowthStage,
  updateBlockCrop,
  type BlockCropAssignment,
} from "@/api/cropAssignments";
import { useCapability } from "@/rbac/useCapability";

interface GrowthStageControlProps {
  blockId: string;
  farmId: string;
  assignment: BlockCropAssignment;
}

export function GrowthStageControl({
  blockId,
  farmId,
  assignment,
}: GrowthStageControlProps): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const arabic = i18n.language?.startsWith("ar") ?? false;
  const canEdit = useCapability("crop_assignment.update", { farmId });
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string>("");

  const taxonomy = useQuery({
    queryKey: ["resolved_taxonomy", assignment.crop_path] as const,
    queryFn: () => getResolvedTaxonomy(assignment.crop_path),
    staleTime: 300_000,
  });
  const history = useQuery({
    queryKey: ["growth_stages", blockId] as const,
    queryFn: () => listGrowthStages(blockId),
    staleTime: 30_000,
  });

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: ["growth_stages", blockId] });
    void queryClient.invalidateQueries({ queryKey: ["block_crops", blockId] });
  };
  const setStage = useMutation({
    mutationFn: (stage: string) =>
      recordGrowthStage(blockId, { stage, block_crop_id: assignment.id }),
    onSuccess: () => {
      setPending("");
      invalidate();
    },
  });
  const setLock = useMutation({
    mutationFn: (locked: boolean) =>
      updateBlockCrop(blockId, assignment.id, { growth_stage_locked: locked }),
    onSuccess: invalidate,
  });

  const stages = taxonomy.data?.phenology_stages?.stages ?? [];
  const ordered = [...stages].sort((a, b) => a.order - b.order);
  const label = (code: string): string => {
    const stage = ordered.find((s) => s.code === code);
    if (!stage) return code;
    return arabic ? (stage.name_ar ?? stage.name_en) : stage.name_en;
  };

  return (
    <section className="mt-3 rounded-md border border-ap-line bg-ap-bg/30 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold text-ap-ink">{t("growthStage.heading")}</h4>
        {assignment.growth_stage_updated_at ? (
          <span className="text-[11px] text-ap-muted">
            {t("growthStage.changedOn", {
              date: assignment.growth_stage_updated_at.slice(0, 10),
            })}
          </span>
        ) : null}
      </div>

      <p className="mt-1 text-sm text-ap-ink">
        {assignment.growth_stage ? (
          <b>{label(assignment.growth_stage)}</b>
        ) : (
          <span className="text-ap-muted">{t("growthStage.unset")}</span>
        )}
      </p>

      {/* Most crops have no calendar, so the stage can never advance by itself.
          An agronomist would otherwise just see a permanently empty field. */}
      {!taxonomy.isLoading && ordered.length === 0 ? (
        <p className="mt-2 rounded border border-ap-warn/40 bg-ap-warn/5 p-2 text-[11px] text-ap-warn">
          {t("growthStage.noCalendar")}
        </p>
      ) : null}

      {canEdit && ordered.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
            {t("growthStage.setTo")}
            <select
              value={pending}
              onChange={(e) => setPending(e.target.value)}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink"
              aria-label={t("growthStage.setTo")}
            >
              <option value="">—</option>
              {ordered.map((s) => (
                <option key={s.code} value={s.code}>
                  {arabic ? (s.name_ar ?? s.name_en) : s.name_en}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!pending || setStage.isPending}
            onClick={() => setStage.mutate(pending)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {setStage.isPending ? t("growthStage.saving") : t("growthStage.record")}
          </button>
        </div>
      ) : null}

      {canEdit ? (
        <label className="mt-2 flex items-start gap-2 text-[11px] text-ap-ink">
          <input
            type="checkbox"
            checked={assignment.growth_stage_locked}
            disabled={setLock.isPending}
            onChange={(e) => setLock.mutate(e.target.checked)}
          />
          <span>
            {t("growthStage.lock")}
            <span className="block text-ap-muted">{t("growthStage.lockHint")}</span>
          </span>
        </label>
      ) : null}

      {setStage.isError || setLock.isError ? (
        <p role="alert" className="mt-2 text-[11px] text-ap-crit">
          {setStage.error?.message ?? setLock.error?.message ?? t("growthStage.failed")}
        </p>
      ) : null}

      {(history.data?.length ?? 0) > 0 ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-[11px] text-ap-muted">
            {t("growthStage.timeline")}
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {(history.data ?? []).slice(0, 8).map((entry) => (
              <li key={entry.id} className="text-[11px] text-ap-muted">
                <span className="font-mono">{entry.transition_date.slice(0, 10)}</span>{" "}
                {label(entry.stage)}{" "}
                <span className="opacity-70">
                  {/* defaultValue keeps an unrecognised source showing as
                      itself rather than as `growthStage.source.<x>`. */}
                  · {t(`growthStage.source.${entry.source}`, { defaultValue: entry.source })}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
