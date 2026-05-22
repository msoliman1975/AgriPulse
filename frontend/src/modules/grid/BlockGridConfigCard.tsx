import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import {
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

  const configQuery = useQuery({
    queryKey: ["grid-config", blockId, productId],
    queryFn: () => getGridConfig(blockId, productId),
  });

  // Seed the input from the active config on first load.
  useEffect(() => {
    if (configQuery.data && cellSize === "") {
      setCellSize(configQuery.data.cell_size_m);
    }
  }, [configQuery.data, cellSize]);

  const parsed = Number(cellSize);
  const isValid = !Number.isNaN(parsed) && parsed > 0;

  const previewQuery = useQuery({
    queryKey: ["grid-config-preview", blockId, productId, parsed],
    queryFn: () => previewCellSize(blockId, productId, parsed),
    enabled: isValid,
  });

  const saveMutation = useMutation({
    mutationFn: () => putGridConfig(blockId, productId, parsed),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grid-config", blockId, productId] });
      queryClient.invalidateQueries({ queryKey: ["grid-cells", blockId] });
    },
  });

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

      {configQuery.data && (
        <p className="mt-3 text-xs text-slate-500">
          {t("subblockGrid.currentConfig", {
            defaultValue: "Active: {{size}}m, {{count}} cells.",
            size: configQuery.data.cell_size_m,
            count: configQuery.data.cell_count,
          })}
        </p>
      )}

      <button
        type="button"
        disabled={!isValid || !previewQuery.data?.valid || saveMutation.isPending}
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
    </section>
  );
}
