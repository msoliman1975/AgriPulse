import { format } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  previewTemplateApply,
  type AppliableTemplate,
  type ApplyRequest,
  type PreviewResponse,
} from "@/api/planTemplates";
import { Modal } from "@/components/Modal";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useAppliableTemplates, useApplyTemplate } from "@/queries/planTemplates";

interface Props {
  farmId: string;
  onClose: () => void;
}

interface BlockSel {
  checked: boolean;
  start_date: string;
}

type Step = 1 | 2 | 3 | 4;

/**
 * 4-step "Apply template" wizard:
 *   1. Pick an appliable (published, crop-matching) template.
 *   2. Pick blocks (pre-checked matching-crop) + per-block start date
 *      (default = planting_date).
 *   3. Season label / year (derived, editable).
 *   4. Preview the resolved schedule (stage-anchored dates + skipped) → apply.
 */
export function ApplyTemplateDialog({ farmId, onClose }: Props): ReactNode {
  const { t } = useTranslation("planTemplates");
  const today = format(new Date(), "yyyy-MM-dd");

  const appliableQ = useAppliableTemplates(farmId);
  const apply = useApplyTemplate(farmId);

  const [step, setStep] = useState<Step>(1);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [blockSel, setBlockSel] = useState<Record<string, BlockSel>>({});
  const [seasonYear, setSeasonYear] = useState<number>(new Date().getFullYear());
  const [seasonLabel, setSeasonLabel] = useState<string>(String(new Date().getFullYear()));
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<{ created: number; skipped: number } | null>(null);

  const templates = useMemo(() => appliableQ.data ?? [], [appliableQ.data]);
  const selected: AppliableTemplate | undefined = useMemo(
    () => templates.find((x) => x.id === templateId),
    [templates, templateId],
  );

  function pickTemplate(tpl: AppliableTemplate): void {
    setTemplateId(tpl.id);
    const seed: Record<string, BlockSel> = {};
    for (const b of tpl.matching_blocks) {
      seed[b.block_id] = { checked: true, start_date: b.planting_date ?? today };
    }
    setBlockSel(seed);
    setStep(2);
  }

  const checkedBlocks = useMemo(
    () => Object.entries(blockSel).filter(([, v]) => v.checked),
    [blockSel],
  );

  function buildRequest(): ApplyRequest {
    return {
      farm_id: farmId,
      season_label: seasonLabel.trim() || String(seasonYear),
      season_year: seasonYear,
      blocks: checkedBlocks.map(([block_id, v]) => ({ block_id, start_date: v.start_date })),
    };
  }

  async function goPreview(): Promise<void> {
    if (!templateId) return;
    setError(null);
    setPreviewLoading(true);
    try {
      const res = await previewTemplateApply(templateId, buildRequest());
      setPreview(res);
      setStep(4);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewLoading(false);
    }
  }

  function doApply(): void {
    if (!templateId) return;
    setError(null);
    apply.mutate(
      { templateId, body: buildRequest() },
      {
        onSuccess: (res) => setApplied({ created: res.activities_created, skipped: res.skipped }),
        onError: (e) => setError(e.message),
      },
    );
  }

  const blockCodeById = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const b of selected?.matching_blocks ?? []) m.set(b.block_id, b.block_code);
    return m;
  }, [selected]);

  return (
    <Modal open onClose={onClose} labelledBy="apply-template-title" className="max-w-3xl">
      <div className="flex items-center justify-between">
        <h2 id="apply-template-title" className="text-lg font-semibold text-ap-ink">
          {t("apply.title")}
        </h2>
        <span className="text-xs text-ap-muted">
          {t("apply.step", { current: step, total: 4 })}
        </span>
      </div>

      {error ? (
        <div className="mt-3 rounded-md border border-ap-crit/40 bg-ap-crit-soft px-3 py-2 text-sm text-ap-crit">
          {error}
        </div>
      ) : null}

      {/* Step 1 — pick template */}
      {step === 1 ? (
        <div className="mt-4">
          {appliableQ.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : templates.length === 0 ? (
            <p className="text-sm text-ap-muted">{t("apply.noTemplates")}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {templates.map((tpl) => (
                <li key={tpl.id}>
                  <button
                    type="button"
                    onClick={() => pickTemplate(tpl)}
                    className="flex w-full items-center justify-between rounded-lg border border-ap-line bg-white p-3 text-start hover:border-ap-primary"
                  >
                    <div>
                      <div className="font-medium text-ap-ink">{tpl.name}</div>
                      <code className="font-mono text-[11px] text-ap-primary">{tpl.crop_path}</code>
                      {tpl.region ? (
                        <span className="ms-2 text-[11px] text-ap-muted">· {tpl.region}</span>
                      ) : null}
                    </div>
                    <Pill kind="neutral">
                      {t("apply.matchingBlocks", { count: tpl.matching_blocks.length })}
                    </Pill>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {/* Step 2 — pick blocks + per-block start date */}
      {step === 2 && selected ? (
        <div className="mt-4 flex flex-col gap-2">
          <p className="text-xs text-ap-muted">{t("apply.blocksHint")}</p>
          {selected.matching_blocks.map((b) => {
            const sel = blockSel[b.block_id] ?? { checked: true, start_date: today };
            return (
              <div
                key={b.block_id}
                className="flex items-center gap-3 rounded-md border border-ap-line bg-white p-2"
              >
                <input
                  type="checkbox"
                  checked={sel.checked}
                  onChange={(e) =>
                    setBlockSel((prev) => ({
                      ...prev,
                      [b.block_id]: { ...sel, checked: e.target.checked },
                    }))
                  }
                  aria-label={b.block_code ?? b.block_id}
                />
                <span className="flex-1 text-sm text-ap-ink">{b.block_code ?? b.block_id}</span>
                <label className="flex items-center gap-1 text-xs text-ap-muted">
                  {t("apply.startDate")}
                  <input
                    type="date"
                    className="input w-auto"
                    value={sel.start_date}
                    onChange={(e) =>
                      setBlockSel((prev) => ({
                        ...prev,
                        [b.block_id]: { ...sel, start_date: e.target.value },
                      }))
                    }
                  />
                </label>
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Step 3 — season */}
      {step === 3 ? (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("apply.seasonLabel")}
            </span>
            <input
              className="input"
              value={seasonLabel}
              onChange={(e) => setSeasonLabel(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("apply.seasonYear")}
            </span>
            <input
              type="number"
              className="input"
              value={seasonYear}
              onChange={(e) => setSeasonYear(Number(e.target.value))}
            />
          </label>
        </div>
      ) : null}

      {/* Step 4 — preview + confirm */}
      {step === 4 ? (
        <div className="mt-4">
          {applied ? (
            <div className="rounded-md border border-ap-primary/40 bg-ap-primary-soft p-4 text-sm text-ap-ink">
              {t("apply.doneSummary", { created: applied.created, skipped: applied.skipped })}
            </div>
          ) : previewLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : preview ? (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-ap-muted">
                {t("apply.previewSummary", {
                  total: preview.total_activities,
                  skipped: preview.total_skipped,
                })}
              </p>
              {preview.blocks.map((blk) => (
                <div key={blk.block_id} className="rounded-md border border-ap-line bg-white p-2">
                  <div className="mb-1 text-sm font-medium text-ap-ink">
                    {blockCodeById.get(blk.block_id) ?? blk.block_code ?? blk.block_id}
                  </div>
                  {blk.activities.length === 0 ? (
                    <p className="text-[11px] text-ap-muted">{t("apply.noActivitiesForBlock")}</p>
                  ) : (
                    <ul className="flex flex-col gap-0.5">
                      {blk.activities.map((a) => (
                        <li
                          key={a.template_activity_id}
                          className="flex items-center justify-between text-[12px] text-ap-ink"
                        >
                          <span>{t(`activityType.${a.activity_type}`, a.activity_type)}</span>
                          <span className="text-ap-muted">
                            {a.scheduled_date}
                            {a.anchored_stage_code ? ` · ${a.anchored_stage_code}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {blk.skipped.length > 0 ? (
                    <p className="mt-1 text-[11px] text-ap-warn">
                      {t("apply.skippedForBlock", { count: blk.skipped.length })}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Footer nav */}
      <div className="mt-5 flex items-center justify-between">
        <button type="button" onClick={onClose} className="text-sm text-ap-muted hover:text-ap-ink">
          {applied ? t("apply.close") : t("apply.cancel")}
        </button>
        {!applied ? (
          <div className="flex items-center gap-2">
            {step > 1 ? (
              <button
                type="button"
                onClick={() => setStep((s) => (s - 1) as Step)}
                className="rounded-md border border-ap-line px-3 py-1.5 text-sm text-ap-muted hover:bg-ap-line/50"
              >
                {t("apply.back")}
              </button>
            ) : null}
            {step === 2 ? (
              <button
                type="button"
                disabled={checkedBlocks.length === 0}
                onClick={() => setStep(3)}
                className="rounded-md bg-ap-primary px-4 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
              >
                {t("apply.next")}
              </button>
            ) : null}
            {step === 3 ? (
              <button
                type="button"
                onClick={() => void goPreview()}
                disabled={previewLoading}
                className="rounded-md bg-ap-primary px-4 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
              >
                {t("apply.preview")}
              </button>
            ) : null}
            {step === 4 ? (
              <button
                type="button"
                onClick={doApply}
                disabled={apply.isPending}
                className="rounded-md bg-ap-primary px-4 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
              >
                {apply.isPending ? t("apply.applying") : t("apply.confirm")}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
