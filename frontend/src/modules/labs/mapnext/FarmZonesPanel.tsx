// Farm-level zone settings: sub-block cell size and anomaly sensitivity.
//
// Replaces save-template-then-apply for these two, the same way imagery and
// weather were replaced. That flow reconciled blocks against the template
// STORED on the server, so an unsaved edit made Apply a no-op — and the
// no-op message blamed the blocks ("Blocks with no grid yet need a cell size
// set on the block first") when the real cause was usually that the farm
// template had never been saved.
//
// The two settings are NOT equally safe, and this panel does not pretend
// they are:
//
//   * anomaly sensitivity is a number read at detection time. Changing it
//     rewrites nothing, so it saves and applies in one action.
//   * cell size RETIRES LIVE GEOMETRY. The replaced grid keeps governing the
//     scenes it already produced and a new one opens at now, so every
//     affected scene has to be reprocessed to be readable under the new
//     zones. That keeps its confirmation step, with the cost stated first.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  applyGrid,
  applyGridCellSize,
  getGridTemplate,
  previewApplyGrid,
  putGridTemplate,
  type GridApplyPreview,
  type GridTemplate,
} from "@/api/farmConfig";

const inputCls =
  "rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const primaryBtn =
  "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-50";
const dangerBtn =
  "h-9 rounded-lg bg-ap-crit px-4 text-sm font-semibold text-white hover:bg-ap-crit/90 disabled:opacity-50";
const ghostBtn =
  "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";

interface Props {
  farmId: string;
  /** Typed back to confirm a rezone — it retires geometry across the farm. */
  farmName: string;
}

export function FarmZonesPanel({ farmId, farmName }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [tpl, setTpl] = useState<GridTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // Cell-size rezone flow: draft → preview → typed confirmation.
  const [cellDraft, setCellDraft] = useState("");
  const [preview, setPreview] = useState<GridApplyPreview | null>(null);
  const [typed, setTyped] = useState("");
  // Blank means "reprocess everything affected"; a number caps the spend.
  const [budget, setBudget] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const got = await getGridTemplate(farmId);
      setTpl(got);
      setCellDraft(got.cell_size_m === null ? "" : String(got.cell_size_m));
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmZones.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [farmId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-xs text-ap-muted">{t("farmZones.loading")}</p>;
  if (!tpl) return <p className="text-xs text-ap-crit">{error}</p>;

  /** Sensitivity rewrites nothing, so it saves and applies in one go. */
  async function commitSensitivity(next: number | null): Promise<void> {
    if (!tpl) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const saved = await putGridTemplate(farmId, { ...tpl, anomaly_z_threshold: next });
      setTpl(saved);
      const counts = await applyGrid(farmId, null, false);
      setNote(
        t("farmZones.sensitivityApplied", {
          touched: counts.blocks_touched,
          total: counts.total_blocks,
        }),
      );
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmZones.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  /** Hand every block back to the tenant default.
   *
   * Without this, pushing a farm sensitivity onto blocks is a one-way door:
   * each block keeps its own override forever and there is no way to say
   * "go back to inheriting". The backend calls it clear_override.
   */
  async function resetToInherited(): Promise<void> {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const counts = await applyGrid(farmId, null, true);
      setNote(
        t("farmZones.inheritApplied", {
          touched: counts.blocks_touched,
          total: counts.total_blocks,
        }),
      );
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmZones.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  /** Cell size retires geometry, so it saves then shows what it would cost. */
  async function previewCellSize(): Promise<void> {
    if (!tpl) return;
    const trimmed = cellDraft.trim();
    const next = trimmed === "" ? null : Number(trimmed);
    if (next !== null && (!Number.isFinite(next) || next <= 0)) {
      setError(t("farmZones.cellSizeInvalid"));
      return;
    }
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      // Saved FIRST, so the preview describes the value on screen. The old
      // flow previewed the stored template, which is how an unsaved edit
      // produced a confident preview of the wrong thing.
      const saved = await putGridTemplate(farmId, { ...tpl, cell_size_m: next });
      setTpl(saved);
      setPreview(await previewApplyGrid(farmId, null, false, "cell_size"));
      setTyped("");
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmZones.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRezone(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const counts = await applyGridCellSize(
        farmId,
        null,
        farmName,
        budget.trim() === "" ? null : Number(budget),
      );
      setNote(
        t("farmZones.rezoneApplied", {
          touched: counts.blocks_touched,
          total: counts.total_blocks,
        }),
      );
      setPreview(null);
      setTyped("");
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmZones.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  const needsConfirm = preview?.requires_confirmation ?? false;
  const confirmOk = !needsConfirm || typed.trim() === farmName.trim();

  return (
    <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
      <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("farmZones.title")}</h3>
      <p className="mb-3 text-xs text-ap-muted">{t("farmZones.intro")}</p>

      {error ? <p className="mb-2 text-xs text-ap-crit">{error}</p> : null}
      {note ? <p className="mb-2 text-xs text-ap-good">{note}</p> : null}

      <label className="mb-3 flex flex-wrap items-center gap-2 text-xs text-ap-muted">
        {t("farmZones.sensitivity")}
        <input
          type="number"
          step="0.1"
          min={0}
          defaultValue={tpl.anomaly_z_threshold ?? ""}
          disabled={busy}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const next = raw === "" ? null : Number(raw);
            if (next !== null && (!Number.isFinite(next) || next < 0)) return;
            if (next !== tpl.anomaly_z_threshold) void commitSensitivity(next);
          }}
          className={inputCls + " w-24"}
        />
        <span className="text-ap-muted">{t("farmZones.sensitivityHint")}</span>
      </label>
      <button
        type="button"
        onClick={() => void resetToInherited()}
        disabled={busy}
        className={ghostBtn + " mb-3 h-7 px-2 text-xs"}
      >
        {t("farmZones.resetToInherited")}
      </button>

      <div className="flex flex-wrap items-end gap-2 border-t border-ap-line pt-3">
        <label className="flex items-center gap-2 text-xs text-ap-muted">
          {t("farmZones.cellSize")}
          <input
            type="number"
            min={1}
            value={cellDraft}
            disabled={busy}
            onChange={(e) => setCellDraft(e.target.value)}
            className={inputCls + " w-24"}
          />
        </label>
        <button
          type="button"
          onClick={() => void previewCellSize()}
          disabled={busy}
          className={ghostBtn}
        >
          {t("farmZones.previewRezone")}
        </button>
      </div>
      <p className="mt-2 text-xs text-ap-muted">{t("farmZones.cellSizeHint")}</p>

      {preview ? (
        <div className="mt-3 space-y-2 rounded-lg border border-ap-line bg-ap-panel p-3">
          <p className="text-xs text-ap-muted">
            {t("farmZones.previewSummary", {
              changed: preview.changed_rows,
              create: preview.create_rows,
              rezone: preview.rezone_rows,
              skipped: preview.skipped_rows,
            })}
          </p>
          {preview.is_noop ? (
            // Says what is actually true, rather than blaming the blocks.
            <p className="text-xs text-ap-warn">{t("farmZones.nothingWouldChange")}</p>
          ) : null}
          {preview.blocked_rows > 0 ? (
            <p className="text-xs text-ap-warn">
              {t("farmZones.blockedRows", { blocked: preview.blocked_rows })}
            </p>
          ) : null}
          {preview.scenes_affected > 0 ? (
            <p className="text-xs text-ap-warn">
              {t("farmZones.scenesAffected", { scenes: preview.scenes_affected })}
            </p>
          ) : null}

          {!preview.is_noop ? (
            <>
              <label className="flex flex-col gap-1 text-xs text-ap-muted">
                {t("farmZones.backfillBudget")}
                <input
                  type="number"
                  min={1}
                  value={budget}
                  placeholder={t("farmZones.backfillBudgetAll")}
                  onChange={(e) => setBudget(e.target.value)}
                  className={inputCls + " w-40"}
                />
              </label>
              {needsConfirm ? (
                <label className="flex flex-col gap-1 text-xs text-ap-muted">
                  {t("farmZones.typeFarmName", { name: farmName })}
                  <input
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    className={inputCls + " w-56"}
                  />
                </label>
              ) : null}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void confirmRezone()}
                  disabled={busy || !confirmOk}
                  className={needsConfirm ? dangerBtn : primaryBtn}
                >
                  {t("farmZones.confirmRezone")}
                </button>
                <button
                  type="button"
                  onClick={() => setPreview(null)}
                  disabled={busy}
                  className={ghostBtn}
                >
                  {t("farmZones.cancel")}
                </button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
