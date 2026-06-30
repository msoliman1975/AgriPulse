import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AnchoredPopup } from "@/components/AnchoredPopup";

import { getGridCellHistory } from "../../api/grid";
import type { IndexCode } from "../../api/indices";

interface Props {
  open: boolean;
  cellId: string | null;
  productId: string | null;
  indexCode: IndexCode;
  value: number | null;
  lat: number | null;
  lon: number | null;
  blockName: string | null;
  // Click pixel coords (relative to the map container) — anchor the card
  // next to the clicked cell. Null falls back to the fixed top-right corner.
  x: number | null;
  y: number | null;
  // Scene timestamp (ISO) of the cell's current value.
  time: string | null;
  // Block-average baseline the backend uses to judge the value good/bad,
  // plus the cell's deviation in std-devs (positive = BELOW the block avg).
  baselineMean: number | null;
  z: number | null;
  // Open cell-scoped recommendations/alerts attributed to this cell (per-cell
  // P2). Empty/omitted when the cell has none.
  cellItems?: CellItem[];
  onClose: () => void;
}

export interface CellItem {
  id: string;
  kind: "rec" | "alert";
  severity: string;
  text: string;
}

function formatSceneTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Compact floating popup for a clicked grid cell. Surfaces the latest
 * min/mean/max, the cell coordinate, its block, the scene timestamp, and
 * the block-average baseline used to flag the cell — plus a (placeholder)
 * "scout this area" action. Card chrome, the descriptive title, and the
 * click-anchoring live in the shared AnchoredPopup wrapper so this and the
 * signal-observation popup look + behave identically. Plain-English inline
 * copy to match the map toolbar (no i18n keys).
 */
export function GridCellPopup({
  open,
  cellId,
  productId,
  indexCode,
  value,
  lat,
  lon,
  blockName,
  x,
  y,
  time,
  baselineMean,
  z,
  cellItems,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const { data } = useQuery({
    queryKey: ["grid-cell-history", cellId, productId, indexCode],
    queryFn: () => {
      if (!cellId || !productId) throw new Error("cellId + productId required");
      return getGridCellHistory(cellId, productId, indexCode);
    },
    enabled: open && cellId !== null && productId !== null,
  });

  if (!open) return null;

  // Latest non-null point drives the min/mean/max readout — same logic
  // as the old GridCellDrawer's CellSummary (newest scene first).
  const latest = data ? [...data.points].reverse().find((p) => p.mean !== null) ?? null : null;
  const headline =
    value != null ? value.toFixed(3) : latest?.mean != null ? Number(latest.mean).toFixed(3) : "—";

  // Baseline status copy + token. Positive z = below the block average
  // (the anomaly-flagged direction); >= 1.5σ-below is what the backend
  // flags (DEFAULT_K).
  let statusLabel = t("gridPopup.status.normal");
  let statusKind: "warn" | "ok" | "neutral" = "neutral";
  let deviationLine = t("gridPopup.aboutAvg");
  let deviationClass = "text-ap-muted";
  if (z != null) {
    if (z >= 1.5) {
      statusLabel = t("gridPopup.status.low");
      statusKind = "warn";
      deviationLine = t("gridPopup.belowAvg", { z: z.toFixed(1) });
      deviationClass = "text-ap-warn";
    } else if (z <= -0.5) {
      statusLabel = t("gridPopup.status.high");
      statusKind = "ok";
      deviationLine = t("gridPopup.aboveAvg", { z: (-z).toFixed(1) });
      deviationClass = "text-ap-primary";
    }
  }
  const statusChipClass =
    statusKind === "warn"
      ? "bg-ap-warn-soft text-ap-warn"
      : statusKind === "ok"
        ? "bg-ap-primary-soft text-ap-primary"
        : "bg-ap-line/70 text-ap-ink";

  return (
    <AnchoredPopup
      x={x}
      y={y}
      title={t("gridPopup.title")}
      subtitle={indexCode.toUpperCase()}
      onClose={onClose}
    >
      <div className="mb-2">
        <p className="text-lg font-semibold text-ap-ink">{headline}</p>
        {time ? (
          <p className="text-[10px] text-ap-muted">
            {t("gridPopup.asOf", { time: formatSceneTime(time) })}
          </p>
        ) : null}
      </div>

      <dl className="mb-2 grid grid-cols-3 gap-1.5">
        <Stat label={t("gridPopup.min")} value={latest?.min ?? null} />
        <Stat label={t("gridPopup.mean")} value={latest?.mean ?? null} />
        <Stat label={t("gridPopup.max")} value={latest?.max ?? null} />
      </dl>

      {/* Block-average baseline — the spatial mean of the cell's block for
          this scene, which is what the backend anomaly detector compares
          each cell against (>= 1.5σ below => flagged). */}
      <div className="mb-2 rounded border border-ap-line p-1.5">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[11px] text-ap-muted">{t("gridPopup.blockAvg")}</span>
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] text-ap-ink">
              {baselineMean != null ? baselineMean.toFixed(3) : "—"}
            </span>
            <span
              className={clsx(
                "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                statusChipClass,
              )}
            >
              {statusLabel}
            </span>
          </span>
        </div>
        <p className={clsx("text-[11px] font-medium", deviationClass)}>{deviationLine}</p>
        <p className="mt-0.5 text-[10px] text-ap-muted">{t("gridPopup.flagHint")}</p>
      </div>

      <div className="space-y-1 text-[11px] text-ap-muted">
        <div className="flex justify-between gap-2">
          <span className="text-ap-muted">{t("gridPopup.coordinate")}</span>
          <span className="font-mono text-ap-ink">
            {lat != null && lon != null ? `${lat.toFixed(5)}, ${lon.toFixed(5)}` : "—"}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-ap-muted">{t("gridPopup.block")}</span>
          <span className="truncate text-ap-ink" title={blockName ?? undefined}>
            {blockName ?? "—"}
          </span>
        </div>
      </div>

      {cellItems && cellItems.length > 0 ? (
        <div className="mt-2 space-y-1 border-t border-ap-line pt-2">
          <p className="text-[10px] font-medium uppercase text-ap-muted">
            {t("gridPopup.zoneActions")}
          </p>
          {cellItems.map((item) => (
            <div key={item.id} className="flex items-start gap-1.5 text-[11px]">
              <span
                className={clsx(
                  "mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                  item.severity === "critical"
                    ? "bg-ap-crit"
                    : item.severity === "warning"
                      ? "bg-ap-warn"
                      : "bg-ap-primary",
                )}
              />
              <span className="text-ap-ink">{item.text}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Placeholder for a future "send a scout task" action — wiring up
          the scouting workflow is out of scope here, so this is a no-op. */}
      <button
        type="button"
        title={t("gridPopup.comingSoon")}
        onClick={() => console.info("Scout this area — coming soon", { cellId, lat, lon })}
        className="mt-2 text-[11px] font-medium text-ap-primary hover:underline"
      >
        {t("gridPopup.scout")}
      </button>
    </AnchoredPopup>
  );
}

function Stat({ label, value }: { label: string; value: string | null }): ReactNode {
  return (
    <div className="rounded border border-ap-line px-1.5 py-1">
      <dt className="text-[10px] text-ap-muted">{label}</dt>
      <dd className="text-[11px] font-medium text-ap-ink">
        {value === null ? "—" : Number(value).toFixed(3)}
      </dd>
    </div>
  );
}
