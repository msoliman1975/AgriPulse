// Map layers, on the top bar.
//
// These are the switches that decide what the map DRAWS AROUND the data:
// where the farm ends, where a block ends, where the mesh lines fall, how
// hard those lines are painted, and what a block is called. They change
// rarely, they are not readings, and they belong nowhere near the datapoint
// control on the map's edge — which is why they are here, spelled out, rather
// than nine rows down a popover nobody opened.
//
// Every control is directly manipulable: a checkbox is a checkbox and a slider
// is a slider. The previous design put both behind a `Layers ▾` chip and then
// behind a `More` card, and the two most-used switches ended up two clicks and
// eight rows from the reader.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BlockLabelField, LayerState } from "../mapnext/ViewBar";

interface Props {
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
  showGrid: boolean;
  onToggleGrid: () => void;
  /** No block on this farm has a sub-block grid configured. */
  gridAvailable: boolean;
  className?: string;
}

export function MapLayerBar({
  layers,
  onLayersChange,
  showGrid,
  onToggleGrid,
  gridAvailable,
  className,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");

  return (
    <div className={"flex min-w-0 items-center gap-3 " + (className ?? "")}>
      <Check
        label={t("layerBar.farmBorders")}
        checked={layers.aoi}
        onChange={() => onLayersChange({ aoi: !layers.aoi })}
      />
      <Check
        label={t("layerBar.blockBorders")}
        checked={layers.borders}
        onChange={() => onLayersChange({ borders: !layers.borders })}
      />
      {/* Cells no longer depend on what the map is drawing. The mesh is
          geometry; only its numbers are per-index, and this console draws the
          outlines without a fill. It greys out for ONE reason now — the farm
          has no zoning — and says so on the bar rather than in a tooltip
          nobody hovers. */}
      <Check
        label={t("layerBar.cells")}
        checked={showGrid}
        disabled={!gridAvailable}
        title={gridAvailable ? undefined : t("layerBar.cellsUnavailable")}
        onChange={onToggleGrid}
      />
      {!gridAvailable ? (
        <span className="flex-none whitespace-nowrap text-xs text-ap-muted">
          {t("layerBar.cellsUnavailableShort")}
        </span>
      ) : null}

      <Rule />

      <MiniSlider
        label={t("layerBar.borderOpacity")}
        title={t("layers.borderOpacity")}
        value={layers.borderOpacity}
        onChange={(v) => onLayersChange({ borderOpacity: v })}
      />

      <Rule />

      <Check
        label={t("layerBar.showLabels")}
        checked={layers.labels}
        onChange={() => onLayersChange({ labels: !layers.labels })}
      />
      {/* Only while labels are on. A picker that changes nothing visible is a
          puzzle, and this one has a second cost: "Crop" fetches the farm's
          crop assignments for the scene date, so an inert picker would also
          spend a request. */}
      {layers.labels ? (
        <Segmented
          value={layers.labelField}
          onChange={(v) => onLayersChange({ labelField: v })}
          options={[
            { value: "name", label: t("layerBar.labelName") },
            { value: "crop", label: t("layerBar.labelCrop") },
          ]}
        />
      ) : null}
    </div>
  );
}

function Rule(): ReactNode {
  return <span className="h-5 w-px flex-none bg-ap-line" aria-hidden="true" />;
}

function Check({
  label,
  checked,
  disabled,
  title,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  title?: string;
  onChange: () => void;
}): ReactNode {
  return (
    <label
      title={title ?? label}
      className={
        "flex flex-none items-center gap-1.5 whitespace-nowrap text-sm " +
        (disabled ? "cursor-not-allowed text-ap-muted/60" : "cursor-pointer text-ap-ink")
      }
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="h-3.5 w-3.5 accent-ap-primary"
      />
      <span>{label}</span>
    </label>
  );
}

/**
 * A 0..1 slider narrow enough for a 48px bar.
 *
 * The percentage is in the title and the accessible name rather than printed
 * beside it: the number costs 32px on a bar that is already the widest thing
 * on the page, and the slider's own position says the same thing.
 */
function MiniSlider({
  label,
  title,
  value,
  onChange,
}: {
  label: string;
  title: string;
  value: number;
  onChange: (v: number) => void;
}): ReactNode {
  const pct = Math.round(value * 100);
  return (
    <label
      title={`${title} — ${pct}%`}
      className="flex flex-none items-center gap-1.5 whitespace-nowrap text-xs text-ap-muted"
    >
      <span>{label}</span>
      <input
        type="range"
        min={0}
        max={100}
        value={pct}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        aria-label={`${title} — ${pct}%`}
        className="w-16 accent-ap-primary"
      />
    </label>
  );
}

function Segmented({
  value,
  onChange,
  options,
}: {
  value: BlockLabelField;
  onChange: (v: BlockLabelField) => void;
  options: { value: BlockLabelField; label: string }[];
}): ReactNode {
  return (
    <div className="flex flex-none overflow-hidden rounded-lg border border-ap-line">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={
            "h-7 whitespace-nowrap px-2 text-xs font-semibold transition-colors " +
            (value === o.value
              ? "bg-ap-primary-soft text-ap-primary"
              : "bg-ap-panel text-ap-muted hover:bg-ap-bg")
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
