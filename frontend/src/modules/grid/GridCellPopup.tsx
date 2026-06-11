import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

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
  onClose: () => void;
}

/**
 * Compact floating popup for a clicked grid cell. Replaces the old
 * full-height GridCellDrawer + sparkline — here we surface just the
 * latest min/mean/max, the cell coordinate, its block, and a
 * (placeholder) "scout this area" action. Plain-English inline copy to
 * match the map toolbar (no i18n keys).
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

  if (!open) return null;

  // Latest non-null point drives the min/mean/max readout — same logic
  // as the old GridCellDrawer's CellSummary (newest scene first).
  const latest = data ? [...data.points].reverse().find((p) => p.mean !== null) ?? null : null;
  const headline =
    value != null ? value.toFixed(3) : latest?.mean != null ? Number(latest.mean).toFixed(3) : "—";

  return (
    <div className="pointer-events-auto absolute top-14 end-4 z-30 w-64 rounded-md border border-ap-line bg-ap-panel p-3 text-xs shadow-lg">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ap-muted">
            {indexCode.toUpperCase()}
          </p>
          <p className="text-lg font-semibold text-ap-ink">{headline}</p>
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
