import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import type { GridWorstCell } from "../../api/grid";
import type { IndexCode } from "../../api/indices";

interface Props {
  showGrid: boolean;
  onToggleGrid: (next: boolean) => void;
  indexCode: IndexCode;
  indexOptions: IndexCode[];
  onIndexChange: (code: IndexCode) => void;
  cellCount: number | null;
  worstCells: GridWorstCell[] | undefined;
  worstLoading: boolean;
  onSelectCell: (cellId: string) => void;
}

/**
 * Map overlay control for the sub-block grid: a show/hide toggle, an
 * index picker, the live cell count, and a short "worst cells" list so a
 * scout can be sent to the exact under-performing spot. Configuration
 * (cell size) lives on the block detail panel, not here.
 */
export function GridOverlayPanel({
  showGrid,
  onToggleGrid,
  indexCode,
  indexOptions,
  onIndexChange,
  cellCount,
  worstCells,
  worstLoading,
  onSelectCell,
}: Props): ReactNode {
  const { t } = useTranslation("farms");

  return (
    <div className="rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow">
      <label className="flex items-center gap-2 text-slate-700">
        <input
          type="checkbox"
          checked={showGrid}
          onChange={(e) => onToggleGrid(e.target.checked)}
          aria-label={t("subblockGrid.toggleAria", { defaultValue: "Show sub-block grid" })}
        />
        <span className="font-medium">
          {t("subblockGrid.toggleLabel", { defaultValue: "Sub-block grid" })}
        </span>
        {showGrid && cellCount != null ? (
          <span className="text-slate-500">
            {t("subblockGrid.cellCount", {
              defaultValue: "{{count}} cells",
              count: cellCount,
            })}
          </span>
        ) : null}
      </label>

      {showGrid ? (
        <div className="mt-2 flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-slate-600">
            <span>{t("subblockGrid.indexLabel", { defaultValue: "Index" })}</span>
            <select
              value={indexCode}
              onChange={(e) => onIndexChange(e.target.value as IndexCode)}
              aria-label={t("subblockGrid.indexLabel", { defaultValue: "Index" })}
              className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs"
            >
              {indexOptions.map((code) => (
                <option key={code} value={code}>
                  {code.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {showGrid ? (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <p className="mb-1 font-medium text-slate-600">
            {t("subblockGrid.worstHeading", {
              defaultValue: "Lowest {{index}} cells",
              index: indexCode.toUpperCase(),
            })}
          </p>
          {worstLoading ? (
            <p className="text-slate-400">
              {t("common.loading", { defaultValue: "Loading…" })}
            </p>
          ) : !worstCells || worstCells.length === 0 ? (
            <p className="text-slate-400">
              {t("subblockGrid.worstEmpty", {
                defaultValue: "No observations yet.",
              })}
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {worstCells.map((cell, i) => (
                <li key={cell.cell_id}>
                  <button
                    type="button"
                    onClick={() => onSelectCell(cell.cell_id)}
                    className="flex w-full items-center justify-between gap-3 rounded px-1.5 py-1 text-left hover:bg-slate-100"
                  >
                    <span className="text-slate-500">
                      {t("subblockGrid.worstRank", {
                        defaultValue: "#{{rank}}",
                        rank: i + 1,
                      })}
                    </span>
                    {cell.ring != null && cell.sector_label ? (
                      <span className="flex-1 truncate text-slate-600">
                        {t("subblockGrid.ringSector", {
                          defaultValue: "ring {{ring}}, {{sector}}",
                          ring: cell.ring,
                          sector: cell.sector_label,
                        })}
                      </span>
                    ) : null}
                    <span className="font-mono font-medium text-slate-800">
                      {cell.mean === null ? "—" : Number(cell.mean).toFixed(3)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
