// A block's own start for heat units (decision D17).
//
// The crop catalogue says where a crop starts counting heat: a calendar date,
// planting, or entry into a stage (for Medjool, pollination). A block whose
// season does not follow that rule, such as an orchard pollinated late, sets
// its own start here; clearing it returns the block to the crop's rule.

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateBlockCrop, type BlockCropAssignment } from "@/api/cropAssignments";
import { useCapability } from "@/rbac/useCapability";

interface HeatUnitStartControlProps {
  blockId: string;
  farmId: string;
  assignment: BlockCropAssignment;
}

export function HeatUnitStartControl({
  blockId,
  farmId,
  assignment,
}: HeatUnitStartControlProps): ReactNode {
  const { t } = useTranslation("farms");
  const canEdit = useCapability("crop_assignment.update", { farmId });
  const queryClient = useQueryClient();
  const saved = assignment.gdd_start_date ?? null;
  const [draft, setDraft] = useState<string>(saved ?? "");

  useEffect(() => setDraft(saved ?? ""), [saved]);

  const save = useMutation({
    mutationFn: (value: string | null) =>
      updateBlockCrop(blockId, assignment.id, { gdd_start_date: value }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["block_crops", blockId] });
    },
  });

  return (
    <section className="mt-3 rounded-md border border-ap-line bg-ap-bg/30 p-3">
      <h4 className="text-xs font-semibold text-ap-ink">{t("heatUnitStart.heading")}</h4>
      <p className="mt-1 text-sm text-ap-ink">
        {saved ? t("heatUnitStart.override", { date: saved }) : t("heatUnitStart.followCrop")}
      </p>
      {canEdit ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
            {t("heatUnitStart.label")}
            <input
              type="date"
              dir="ltr"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink"
              aria-label={t("heatUnitStart.label")}
            />
          </label>
          <button
            type="button"
            disabled={save.isPending || (draft || null) === saved}
            onClick={() => save.mutate(draft || null)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {save.isPending ? t("heatUnitStart.saving") : t("heatUnitStart.save")}
          </button>
          {saved ? (
            <button
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate(null)}
              className="rounded-md border border-ap-line px-3 py-1.5 text-xs text-ap-ink hover:bg-ap-bg disabled:opacity-60"
            >
              {t("heatUnitStart.clear")}
            </button>
          ) : null}
        </div>
      ) : null}
      {canEdit ? <p className="mt-1 text-[11px] text-ap-muted">{t("heatUnitStart.hint")}</p> : null}
      {save.isError ? (
        <p role="alert" className="mt-2 text-[11px] text-ap-crit">
          {save.error?.message ?? t("heatUnitStart.failed")}
        </p>
      ) : null}
    </section>
  );
}
