import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import {
  backfillGrid,
  getGridConfig,
  previewCellSize,
  putGridConfig,
} from "../../api/grid";

interface Props {
  blockId: string;
  productId: string;
}

/**
 * Block-detail card for configuring sub-block grid cell size.
 *
 * Shows the current active config (if any), a numeric input for the
 * desired cell size, a live preview ("at 20m, this block will have 312
 * cells") backed by the preview API, and a Save button that writes the
 * new config + regenerates cells server-side.
 */
export function BlockGridConfigCard({ blockId, productId }: Props): ReactNode {
  const { t } = useTranslation("farms");
  const queryClient = useQueryClient();
  const [cellSize, setCellSize] = useState<string>("");
  // Per-block anomaly threshold override. Empty string = inherit the
  // tenant/platform default (sent as null).
  const [threshold, setThreshold] = useState<string>("");

  const configQuery = useQuery({
    queryKey: ["grid-config", blockId, productId],
    queryFn: () => getGridConfig(blockId, productId),
  });

  // Seed the inputs from the active config once, when it first loads.
  // A ref (not `cellSize === ""`) because an empty threshold is a valid
  // "inherited" state we must not keep re-seeding over.
  const seededRef = useRef(false);
  useEffect(() => {
    if (configQuery.data && !seededRef.current) {
      setCellSize(configQuery.data.cell_size_m);
      setThreshold(configQuery.data.anomaly_z_threshold ?? "");
      seededRef.current = true;
    }
  }, [configQuery.data]);

  const parsed = Number(cellSize);
  const isValid = !Number.isNaN(parsed) && parsed > 0;
  const thresholdTrimmed = threshold.trim();
  const thresholdParsed = thresholdTrimmed === "" ? null : Number(thresholdTrimmed);
  const thresholdValid =
    thresholdParsed === null || (!Number.isNaN(thresholdParsed) && thresholdParsed > 0);

  const previewQuery = useQuery({
    queryKey: ["grid-config-preview", blockId, productId, parsed],
    queryFn: () => previewCellSize(blockId, productId, parsed),
    enabled: isValid,
  });

  const saveMutation = useMutation({
    mutationFn: () => putGridConfig(blockId, productId, parsed, thresholdParsed),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grid-config", blockId, productId] });
      queryClient.invalidateQueries({ queryKey: ["grid-cells", blockId] });
    },
  });

  const backfillMutation = useMutation({
    mutationFn: () => backfillGrid(blockId, productId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grid-cells", blockId] });
    },
  });

  // A rezone (changing the cell size on an existing grid) retires the old
  // cells and generates new ones — the new grid has no history until the
  // next scene, so warn + point at backfill.
  const isRezone =
    configQuery.data != null &&
    isValid &&
    Number(configQuery.data.cell_size_m) !== parsed;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-base font-semibold text-slate-800">
        {t("subblockGrid.cardTitle", { defaultValue: "Sub-block grid" })}
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        {t("subblockGrid.cardSubtitle", {
          defaultValue:
            "Divide this block into smaller cells so per-scene index aggregates pinpoint where issues appear.",
        })}
      </p>

      <label className="mt-3 block text-sm font-medium text-slate-700">
        {t("subblockGrid.cellSizeLabel", { defaultValue: "Cell size (metres)" })}
        <input
          type="number"
          min={1}
          step={1}
          value={cellSize}
          onChange={(e) => setCellSize(e.target.value)}
          className="mt-1 block w-32 rounded border border-slate-300 px-2 py-1 text-sm"
          aria-label={t("subblockGrid.cellSizeLabel", { defaultValue: "Cell size (metres)" })}
        />
      </label>

      {previewQuery.data && (
        <div
          className={`mt-3 rounded-md p-3 text-sm ${
            previewQuery.data.valid
              ? "border border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border border-amber-200 bg-amber-50 text-amber-800"
          }`}
          role="status"
        >
          {previewQuery.data.valid ? (
            <>
              {t("subblockGrid.previewOk", {
                defaultValue:
                  "At {{size}}m, this block will have {{count}} cells ({{ppc}} pixels per cell).",
                size: previewQuery.data.cell_size_m,
                count: previewQuery.data.estimated_cells,
                ppc: previewQuery.data.pixels_per_cell,
              })}
            </>
          ) : (
            <>{previewQuery.data.error}</>
          )}
        </div>
      )}

      <label className="mt-3 block text-sm font-medium text-slate-700">
        {t("subblockGrid.thresholdLabel", { defaultValue: "Anomaly sensitivity (z-score)" })}
        <input
          type="number"
          min={0}
          step="0.1"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          placeholder={t("subblockGrid.thresholdInherit", { defaultValue: "Inherited" })}
          className="mt-1 block w-32 rounded border border-slate-300 px-2 py-1 text-sm"
          aria-label={t("subblockGrid.thresholdLabel", {
            defaultValue: "Anomaly sensitivity (z-score)",
          })}
        />
      </label>
      <p className="mt-1 text-xs text-slate-500">
        {t("subblockGrid.thresholdHelp", {
          defaultValue:
            "Std-devs below the field average before a cell is flagged. Lower = more sensitive. Leave blank to inherit the tenant default.",
        })}
      </p>
      {!thresholdValid && (
        <p className="mt-1 text-xs text-amber-600">
          {t("subblockGrid.thresholdInvalid", {
            defaultValue: "Enter a positive number, or leave blank to inherit.",
          })}
        </p>
      )}

      {configQuery.data && (
        <p className="mt-3 text-xs text-slate-500">
          {t("subblockGrid.currentConfig", {
            defaultValue: "Active: {{size}}m, {{count}} cells.",
            size: configQuery.data.cell_size_m,
            count: configQuery.data.cell_count,
          })}
        </p>
      )}

      {isRezone && (
        <p
          className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"
          role="status"
        >
          {t("subblockGrid.rezoneWarning", {
            defaultValue:
              "Changing the cell size retires the current grid and builds new cells. The new grid has no history until the next scene — use “Backfill” below to repopulate it from past scenes.",
          })}
        </p>
      )}

      <button
        type="button"
        disabled={
          !isValid || !thresholdValid || !previewQuery.data?.valid || saveMutation.isPending
        }
        onClick={() => saveMutation.mutate()}
        className="mt-3 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:bg-slate-300"
      >
        {saveMutation.isPending
          ? t("common.saving", { defaultValue: "Saving…" })
          : configQuery.data
            ? t("subblockGrid.replace", { defaultValue: "Replace grid" })
            : t("subblockGrid.create", { defaultValue: "Create grid" })}
      </button>

      {saveMutation.isError && (
        <p className="mt-2 text-xs text-red-600">
          {t("subblockGrid.saveError", { defaultValue: "Could not save grid config." })}
        </p>
      )}

      {configQuery.data && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="text-xs font-medium text-slate-600">
            {t("subblockGrid.backfillHeading", { defaultValue: "Backfill history" })}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {t("subblockGrid.backfillHelp", {
              defaultValue:
                "Re-process past scenes onto the current cells. Useful after a rezone. This re-reads imagery and can take a while.",
            })}
          </p>
          <button
            type="button"
            disabled={backfillMutation.isPending}
            onClick={() => backfillMutation.mutate()}
            className="mt-2 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {backfillMutation.isPending
              ? t("subblockGrid.backfillPending", { defaultValue: "Queuing…" })
              : t("subblockGrid.backfillButton", { defaultValue: "Backfill historical scenes" })}
          </button>
          {backfillMutation.isSuccess && (
            <p className="mt-2 text-xs text-emerald-700">
              {t("subblockGrid.backfillQueued", {
                defaultValue: "Queued {{count}} scene(s). Cells repopulate as they finish.",
                count: backfillMutation.data.scenes_queued,
              })}
            </p>
          )}
          {backfillMutation.isError && (
            <p className="mt-2 text-xs text-red-600">
              {t("subblockGrid.backfillError", { defaultValue: "Could not start backfill." })}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
