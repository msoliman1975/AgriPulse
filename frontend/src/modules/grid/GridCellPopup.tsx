import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

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
  onClose: () => void;
}

// Offset the card from the click point so it doesn't sit under the cursor.
const ANCHOR_OFFSET = 10;
// Keep the card at least this far from the parent container's edges.
const EDGE_PAD = 4;

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
 * "scout this area" action. Anchored next to the clicked cell when click
 * coords are supplied; otherwise pinned top-right. Plain-English inline
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
  onClose,
}: Props): ReactNode {
  const { data } = useQuery({
    queryKey: ["grid-cell-history", cellId, productId, indexCode],
    queryFn: () => {
      if (!cellId || !productId) throw new Error("cellId + productId required");
      return getGridCellHistory(cellId, productId, indexCode);
    },
    enabled: open && cellId !== null && productId !== null,
  });

  const anchored = x !== null && y !== null;
  const cardRef = useRef<HTMLDivElement | null>(null);
  // Adjusted (clamped/flipped) position once we can measure the card. Until
  // then we render at the raw offset to avoid a frame at (0,0).
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !anchored || x === null || y === null) {
      setPos(null);
      return;
    }
    const card = cardRef.current;
    // offsetParent is the nearest positioned ancestor — the map container
    // (`relative flex-1 overflow-hidden`) that wraps both the canvas and
    // this popup, so its rect shares the same coordinate space as `x`/`y`.
    const parent = card?.offsetParent as HTMLElement | null;
    if (!card || !parent) return;
    const cardRect = card.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    const w = cardRect.width;
    const h = cardRect.height;
    const maxLeft = parentRect.width - w - EDGE_PAD;
    const maxTop = parentRect.height - h - EDGE_PAD;

    let left = x + ANCHOR_OFFSET;
    let top = y + ANCHOR_OFFSET;
    // If we'd overflow the right edge, flip to the left of the click.
    if (left > maxLeft) left = x - w - ANCHOR_OFFSET;
    // If we'd overflow the bottom edge, flip above the click.
    if (top > maxTop) top = y - h - ANCHOR_OFFSET;
    // Clamp inside the container regardless (covers tiny containers / flips
    // that still overshoot).
    left = Math.max(EDGE_PAD, Math.min(left, maxLeft));
    top = Math.max(EDGE_PAD, Math.min(top, maxTop));
    setPos({ left, top });
  }, [open, anchored, x, y, value, baselineMean, z, time, blockName, data]);

  if (!open) return null;

  // Latest non-null point drives the min/mean/max readout — same logic
  // as the old GridCellDrawer's CellSummary (newest scene first).
  const latest = data ? [...data.points].reverse().find((p) => p.mean !== null) ?? null : null;
  const headline =
    value != null ? value.toFixed(3) : latest?.mean != null ? Number(latest.mean).toFixed(3) : "—";

  // When anchored, position via inline style (and drop the fixed-corner
  // Tailwind classes). Until measured, render at the raw offset.
  const anchorStyle =
    anchored && x !== null && y !== null
      ? ({
          position: "absolute",
          left: pos?.left ?? x + ANCHOR_OFFSET,
          top: pos?.top ?? y + ANCHOR_OFFSET,
        } as const)
      : undefined;

  // Baseline status copy + token. Positive z = below the block average
  // (the anomaly-flagged direction); >= 1.5σ-below is what the backend
  // flags (DEFAULT_K).
  let statusLabel = "Normal";
  let statusKind: "warn" | "ok" | "neutral" = "neutral";
  let deviationLine = "~ avg";
  let deviationClass = "text-ap-muted";
  if (z != null) {
    if (z >= 1.5) {
      statusLabel = "Low";
      statusKind = "warn";
      deviationLine = `${z.toFixed(1)}σ below avg`;
      deviationClass = "text-ap-warn";
    } else if (z <= -0.5) {
      statusLabel = "High";
      statusKind = "ok";
      deviationLine = `${(-z).toFixed(1)}σ above avg`;
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
    <div
      ref={cardRef}
      style={anchorStyle}
      className={clsx(
        "pointer-events-auto z-30 w-64 rounded-md border border-ap-line bg-ap-panel p-3 text-xs shadow-lg",
        !anchored && "absolute top-14 end-4",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ap-muted">
            {indexCode.toUpperCase()}
          </p>
          <p className="text-lg font-semibold text-ap-ink">{headline}</p>
          {time ? <p className="text-[10px] text-ap-muted">as of {formatSceneTime(time)}</p> : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded p-0.5 text-ap-muted hover:bg-ap-bg hover:text-ap-ink"
        >
          ✕
        </button>
      </div>

      <dl className="mb-2 grid grid-cols-3 gap-1.5">
        <Stat label="Min" value={latest?.min ?? null} />
        <Stat label="Mean" value={latest?.mean ?? null} />
        <Stat label="Max" value={latest?.max ?? null} />
      </dl>

      {/* Block-average baseline — the spatial mean of the cell's block for
          this scene, which is what the backend anomaly detector compares
          each cell against (>= 1.5σ below => flagged). */}
      <div className="mb-2 rounded border border-ap-line p-1.5">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[11px] text-ap-muted">Block avg</span>
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
        <p className="mt-0.5 text-[10px] text-ap-muted">
          Flagged when ≥1.5σ below the block average.
        </p>
      </div>

      <div className="space-y-1 text-[11px] text-ap-muted">
        <div className="flex justify-between gap-2">
          <span className="text-ap-muted">Coordinate</span>
          <span className="font-mono text-ap-ink">
            {lat != null && lon != null ? `${lat.toFixed(5)}, ${lon.toFixed(5)}` : "—"}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-ap-muted">Block</span>
          <span className="truncate text-ap-ink" title={blockName ?? undefined}>
            {blockName ?? "—"}
          </span>
        </div>
      </div>

      {/* Placeholder for a future "send a scout task" action — wiring up
          the scouting workflow is out of scope here, so this is a no-op. */}
      <button
        type="button"
        title="Coming soon"
        onClick={() => console.info("Scout this area — coming soon", { cellId, lat, lon })}
        className="mt-2 text-[11px] font-medium text-ap-primary hover:underline"
      >
        Scout this area →
      </button>
    </div>
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
