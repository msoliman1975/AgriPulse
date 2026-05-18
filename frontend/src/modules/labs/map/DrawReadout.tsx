import { formatArea, formatDistance } from "./geo";
import type { DrawProgress } from "./MapCanvas";

interface Props {
  progress: DrawProgress | null;
  onCancel: () => void;
}

// Small overlay shown in the top-right of the map while a polygon draw
// is in progress. Surfaces live area / perimeter / vertex count so the
// user can size the polygon before committing — previously the area
// was only computed AFTER finishing the polygon, which meant the user
// had to either guess or trash-and-retry to get a target size.
//
// Also surfaces the mapbox-gl-draw keyboard shortcuts (Esc to cancel,
// Enter to finish) which exist by default but weren't documented
// anywhere in the UI.
export function DrawReadout({ progress, onCancel }: Props) {
  if (!progress) return null;

  const targetLabel =
    progress.target === "block" ? "Block" : progress.target === "farm_aoi" ? "Farm AOI" : "Polygon";

  const canFinish = progress.vertices >= 3;

  return (
    <div
      className="absolute right-2 top-2 z-10 min-w-[180px] rounded-md border border-slate-300 bg-white/95 p-2 text-xs shadow-md"
      role="status"
      aria-live="polite"
    >
      <div className="mb-1 flex items-center justify-between gap-3">
        <span className="font-semibold text-slate-900">Drawing {targetLabel}</span>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-100"
          aria-label="Cancel draw"
        >
          Cancel
        </button>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular-nums text-slate-700">
        <dt className="text-slate-500">Vertices</dt>
        <dd className="text-right">{progress.vertices}</dd>
        <dt className="text-slate-500">Area</dt>
        <dd className="text-right">{formatArea(progress.areaM2)}</dd>
        <dt className="text-slate-500">Perimeter</dt>
        <dd className="text-right">{formatDistance(progress.perimeterM)}</dd>
      </dl>

      <div className="mt-1.5 border-t border-slate-200 pt-1 text-[10px] leading-tight text-slate-500">
        {canFinish ? (
          <>
            <kbd className="rounded border border-slate-300 bg-slate-50 px-1">Enter</kbd> or
            double-click to finish
          </>
        ) : (
          <>
            Click {3 - progress.vertices} more vertex{3 - progress.vertices === 1 ? "" : "es"} to
            finish
          </>
        )}
        <span className="mx-1">·</span>
        <kbd className="rounded border border-slate-300 bg-slate-50 px-1">Esc</kbd> cancels
      </div>
    </div>
  );
}
