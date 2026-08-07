import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PixelGrid } from "@/api/observer";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";

/**
 * Pixel → cell → block, with the arithmetic shown rather than asserted.
 *
 * When a cell is selected the panel lists exactly the pixels the pipeline
 * aggregated for it, sums them in front of you, and puts the result next to
 * the *stored* cell mean. Agreement is the normal case; disagreement is a
 * finding, and the panel says which it is instead of quietly rendering one
 * number.
 *
 * The cell/block pixel counts deliberately do not reconcile, and the footer
 * explains why: cells claim a pixel by its centre, the block AOI by footprint
 * touch. Without that sentence the mismatch reads as a bug.
 */

function fmt(v: number | null | undefined, digits = 4): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

export function CellDrillPanel({
  grid,
  selectedCellId,
  onClear,
  isFetching,
}: {
  grid: PixelGrid | undefined;
  selectedCellId: string | null;
  onClear: () => void;
  isFetching: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");

  if (!grid) return null;

  const cell = grid.cells.find((c) => c.cell_id === selectedCellId) ?? null;
  const withValue = grid.pixels.filter((p) => p.value !== null);
  const agrees =
    grid.stored_cell_mean !== null &&
    grid.recomputed_mean !== null &&
    Math.abs(grid.stored_cell_mean - grid.recomputed_mean) <= 0.0001;

  return (
    <Card
      title={
        cell
          ? t("observer.cells.titleSelected", { label: `R${cell.row_idx}C${cell.col_idx}` })
          : t("observer.cells.title")
      }
      actions={
        <div className="flex items-center gap-2">
          {isFetching ? <Pill kind="info">{t("observer.cells.loading")}</Pill> : null}
          {selectedCellId ? (
            <Button size="sm" variant="ghost" onClick={onClear}>
              {t("observer.cells.clear")}
            </Button>
          ) : null}
        </div>
      }
    >
      {!selectedCellId ? (
        <>
          <p className="text-xs text-ap-muted">{t("observer.cells.prompt")}</p>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            <dt className="text-ap-muted">{t("observer.cells.blockMean")}</dt>
            <dd className="font-semibold tabular-nums">{fmt(grid.block_mean)}</dd>
            <dt className="text-ap-muted">{t("observer.cells.blockPixels")}</dt>
            <dd className="tabular-nums">
              {grid.block_valid} / {grid.block_total}
            </dd>
            <dt className="text-ap-muted">{t("observer.cells.cellCount")}</dt>
            <dd className="tabular-nums">{grid.cells.length}</dd>
            <dt className="text-ap-muted">{t("observer.cells.resolution")}</dt>
            <dd className="tabular-nums">{grid.resolution_m.toFixed(2)} m</dd>
          </dl>
          {grid.truncated ? (
            <p className="mt-3 border-s-2 border-ap-warn ps-3 text-xs">
              {t("observer.cells.truncated", {
                shown: grid.returned_pixel_count,
                total: grid.aoi_pixel_count,
              })}
            </p>
          ) : null}
        </>
      ) : (
        <div className="space-y-4">
          <section>
            <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
              {t("observer.cells.pixelsIn", { n: grid.pixels.length })}
            </p>
            <div className="flex flex-wrap gap-1">
              {grid.pixels.map((p) => (
                <span
                  key={`${p.row}-${p.col}`}
                  title={`row ${p.row}, col ${p.col}${p.masked ? " — cloud-masked" : ""}`}
                  className={clsx(
                    "rounded border px-1.5 py-0.5 font-mono text-[0.6875rem] tabular-nums",
                    p.value === null
                      ? "border-ap-line bg-ap-line/30 text-ap-muted"
                      : "border-ap-primary/30 bg-ap-primary-soft/40",
                  )}
                >
                  {p.value === null ? (p.masked ? "masked" : "no data") : p.value.toFixed(4)}
                </span>
              ))}
            </div>
          </section>

          <section>
            <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
              {t("observer.cells.howAggregated")}
            </p>
            <pre className="whitespace-pre-wrap rounded bg-ap-bg/60 p-3 font-mono text-xs leading-relaxed">
              {t("observer.cells.meanOf", { n: grid.recomputed_valid })}
              {"\n= ("}
              {withValue.map((p) => p.value?.toFixed(4)).join(" + ")}
              {`) / ${grid.recomputed_valid}`}
              {"\n= "}
              {fmt(grid.recomputed_mean)}
            </pre>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-ap-muted">{t("observer.cells.storedCell")}</span>
              <span className="font-semibold tabular-nums">{fmt(grid.stored_cell_mean)}</span>
              {grid.stored_cell_mean !== null ? (
                <Pill kind={agrees ? "ok" : "crit"}>
                  {agrees ? t("observer.cells.agrees") : t("observer.cells.disagrees")}
                </Pill>
              ) : (
                <Pill kind="warn">{t("observer.cells.noStoredRow")}</Pill>
              )}
            </div>
          </section>

          <section>
            <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
              {t("observer.cells.rollsUp")}
            </p>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Chip label={t("observer.cells.pixels")} value={String(grid.recomputed_valid)} />
              <span className="text-ap-muted">→</span>
              <Chip
                label={`${t("observer.cells.cell")} R${cell?.row_idx}C${cell?.col_idx}`}
                value={fmt(grid.stored_cell_mean)}
                sub={`${grid.stored_cell_valid ?? 0} px`}
              />
              <span className="text-ap-muted">→</span>
              <Chip
                label={t("observer.cells.block")}
                value={fmt(grid.block_mean)}
                sub={`${grid.block_valid ?? 0} / ${grid.block_total ?? 0} px`}
              />
            </div>
          </section>

          <p className="border-s-2 border-ap-accent ps-3 text-xs text-ap-muted">
            {t("observer.cells.membership")}
          </p>
        </div>
      )}
    </Card>
  );
}

function Chip({ label, value, sub }: { label: string; value: string; sub?: string }): ReactNode {
  return (
    <div className="min-w-[6.5rem] rounded border border-ap-line bg-ap-bg/40 px-3 py-2">
      <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-ap-muted">
        {label}
      </div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
      {sub ? <div className="text-[0.625rem] text-ap-muted">{sub}</div> : null}
    </div>
  );
}
