// Layers, on the map instead of in a menu.
//
// The console used to hide every layer behind a `Layers ▾` chip in the view
// bar: one click to open, a list of eleven identical toggle rows, and no way
// to tell from the closed state what was on. The two switches an operator
// actually reaches for — the index pixels and the sub-block mesh — were the
// eighth and ninth rows down.
//
// The pattern here is the one every mapping product converged on: a small
// stack of picture cards in the map's bottom-left corner. A card shows what
// the layer looks like, so it is recognised rather than read, and its on/off
// state is visible without opening anything. The long tail — outlines,
// labels, opacity, the mark legend — lives behind one "More" card, which is
// the right place for settings somebody changes once a season.
//
// The thumbnails are drawn from the SAME sources the map draws from: the
// index ramp comes out of `indexClasses`, so a class colour cannot change on
// the map and stay stale on the card.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AnyIndexCode } from "@/api/indices";
import { Card } from "@/components/Card";
import { MarkerLegend } from "../map/MarkerLegend";
import { INDEX_META } from "../mapnext/constants";
import type { LayerState } from "../mapnext/ViewBar";
import { classesFor } from "./indexClasses";

interface Props {
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
  /** The index the pixel card previews and the mesh is coloured by. */
  activeIndex: AnyIndexCode;
  showPixels: boolean;
  onTogglePixels: () => void;
  pixelsAvailable: boolean;
  showGrid: boolean;
  onToggleGrid: () => void;
  gridAvailable: boolean;
  /** The farm has zoning, but this index cannot use it — thermal only. */
  gridUnavailableForIndex?: boolean;
  className?: string;
}

/**
 * A layer card: thumbnail over a caption, pressed when the layer is on.
 *
 * Fixed 64px so a row of them reads as a strip rather than as buttons of
 * assorted widths, and small enough that three plus "More" clear the scene
 * timeline's scroll bar on a 1280px map.
 */
function LayerCard({
  label,
  hint,
  on,
  disabled,
  onClick,
  children,
}: {
  label: string;
  hint?: string | null;
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-pressed={disabled ? undefined : on}
      title={hint ? `${label} — ${hint}` : label}
      className={
        "group w-16 flex-none overflow-hidden rounded-lg border bg-ap-panel text-center shadow-card transition-colors " +
        (disabled
          ? "cursor-not-allowed border-ap-line opacity-50"
          : on
            ? "border-ap-primary"
            : "border-ap-line hover:border-ap-primary/60")
      }
    >
      <span className="block h-11 w-full overflow-hidden" aria-hidden="true">
        {children}
      </span>
      <span
        className={
          "block truncate px-1 py-0.5 text-[10px] font-semibold leading-tight " +
          (on && !disabled ? "bg-ap-primary-soft text-ap-primary" : "text-ap-muted")
        }
      >
        {label}
      </span>
    </button>
  );
}

/** Satellite thumbnail — the bare base map, drawn as its own dominant tones. */
function SatelliteThumb(): ReactNode {
  return (
    <span
      className="block h-full w-full"
      style={{
        background:
          "radial-gradient(circle at 30% 35%, #8a7f63 0 28%, transparent 29%)," +
          "radial-gradient(circle at 72% 68%, #6f6a4e 0 22%, transparent 23%)," +
          "linear-gradient(135deg, #b5ad8e 0%, #9a9273 100%)",
      }}
    />
  );
}

/** Index thumbnail — the active index's own class ramp, left to right. */
function PixelThumb({ code }: { code: AnyIndexCode }): ReactNode {
  const colors = classesFor(code).map((c) => c.color);
  return (
    <span className="flex h-full w-full">
      {colors.map((c, i) => (
        <span key={i} className="h-full flex-1" style={{ background: c }} />
      ))}
    </span>
  );
}

/** Mesh thumbnail — cells over a muted version of the index ramp. */
function GridThumb({ code }: { code: AnyIndexCode }): ReactNode {
  const colors = classesFor(code).map((c) => c.color);
  return (
    <span className="relative block h-full w-full">
      <span className="absolute inset-0 flex opacity-70">
        {colors.map((c, i) => (
          <span key={i} className="h-full flex-1" style={{ background: c }} />
        ))}
      </span>
      <span
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(255,255,255,.85) 1px, transparent 1px)," +
            "linear-gradient(to bottom, rgba(255,255,255,.85) 1px, transparent 1px)",
          backgroundSize: "11px 11px",
        }}
      />
    </span>
  );
}

/** "More" thumbnail — the marks the panel behind it explains. */
function MoreThumb(): ReactNode {
  return (
    <span className="grid h-full w-full place-items-center bg-ap-bg text-base text-ap-muted">
      ⚑ ◇ ▢
    </span>
  );
}

export function MapLayersControl({
  layers,
  onLayersChange,
  activeIndex,
  showPixels,
  onTogglePixels,
  pixelsAvailable,
  showGrid,
  onToggleGrid,
  gridAvailable,
  gridUnavailableForIndex = false,
  className,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on an outside click and on Escape. The panel sits over the map, and
  // a panel that only closes via its own button is one an operator leaves
  // open and then complains the map is small.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const gridDisabled = !gridAvailable || gridUnavailableForIndex;

  return (
    <div ref={rootRef} className={className}>
      {/* The panel opens ABOVE the cards, so the cards never move under the
          pointer that just clicked them. */}
      {open ? (
        <Card
          className="mb-2 max-h-[62vh] w-[268px] overflow-y-auto bg-ap-panel/98 p-1 shadow-card"
          noPadding
        >
          <Heading>{t("viewbar.mapLayers")}</Heading>
          <Toggle
            label={`🟦 ${t("layers.aoi")}`}
            on={layers.aoi}
            onClick={() => onLayersChange({ aoi: !layers.aoi })}
          />
          <Toggle
            label={`▦ ${t("layers.blocks")}`}
            on={layers.blocks}
            onClick={() => onLayersChange({ blocks: !layers.blocks })}
          />
          <Toggle
            label={`▢ ${t("layers.borders")}`}
            on={layers.borders}
            onClick={() => onLayersChange({ borders: !layers.borders })}
          />
          <Toggle
            label={`🅰 ${t("layers.labels")}`}
            on={layers.labels}
            onClick={() => onLayersChange({ labels: !layers.labels })}
          />

          <Divider />
          <Toggle
            label={`⚑ ${t("layers.flags")}`}
            on={layers.flags}
            onClick={() => onLayersChange({ flags: !layers.flags })}
          />
          {/* Nested under the layer it filters, and absent while that layer is
              off — a checkbox that changes nothing visible is a puzzle. */}
          {layers.flags ? (
            <Toggle
              label={`↳ ${t("layers.flagsOpenOnly")}`}
              on={layers.flagsOpenOnly}
              onClick={() => onLayersChange({ flagsOpenOnly: !layers.flagsOpenOnly })}
            />
          ) : null}
          <Toggle
            label={`◇ ${t("layers.signals")}`}
            on={layers.signals}
            onClick={() => onLayersChange({ signals: !layers.signals })}
          />

          <Divider />
          <Slider
            label={t("layers.borderOpacity")}
            value={layers.borderOpacity}
            onChange={(v) => onLayersChange({ borderOpacity: v })}
          />
          <Slider
            label={t("layers.fillOpacity")}
            value={layers.fillOpacity}
            onChange={(v) => onLayersChange({ fillOpacity: v })}
          />

          {/* The legend belongs with the switches for the very layers it
              explains: "what is that mark" and "how do I turn it off" are
              asked by the same person, seconds apart. */}
          <Divider />
          <MarkerLegend />
        </Card>
      ) : null}

      <div className="flex items-end gap-1.5">
        {/* Satellite is the base map and is always drawn — the card is here to
            name what the reader is looking at, and to anchor the strip. It has
            no off state because there is nothing behind it. */}
        <LayerCard
          label={t("layerCards.satellite")}
          hint={t("layerCards.satelliteHint")}
          on
          disabled
          onClick={() => undefined}
        >
          <SatelliteThumb />
        </LayerCard>

        <LayerCard
          label={INDEX_META[activeIndex].label}
          hint={pixelsAvailable ? t("layerCards.pixelsHint") : t("mapDock.pixelsUnavailable")}
          on={showPixels}
          disabled={!pixelsAvailable}
          onClick={onTogglePixels}
        >
          <PixelThumb code={activeIndex} />
        </LayerCard>

        <LayerCard
          // A card caption has 64px, and "Sub-block grid" truncates to
          // "Sub-bloc…" — which names nothing. The full phrase is on the
          // toggle inside the panel and in the hover title.
          label={t("layerCards.grid")}
          hint={
            gridUnavailableForIndex
              ? t("mapDock.gridNotForThisIndex")
              : gridAvailable
                ? t("layerCards.gridHint")
                : t("mapDock.gridUnavailable")
          }
          on={showGrid && !gridUnavailableForIndex}
          disabled={gridDisabled}
          onClick={onToggleGrid}
        >
          <GridThumb code={activeIndex} />
        </LayerCard>

        <LayerCard
          label={t("layerCards.more")}
          hint={t("layerCards.moreHint")}
          on={open}
          onClick={() => setOpen((o) => !o)}
        >
          <MoreThumb />
        </LayerCard>
      </div>
    </div>
  );
}

function Heading({ children }: { children: ReactNode }): ReactNode {
  return (
    <p className="px-2.5 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-wide text-ap-muted">
      {children}
    </p>
  );
}

function Divider(): ReactNode {
  return <div className="my-1 border-t border-ap-line" />;
}

function Toggle({
  label,
  on,
  onClick,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 hover:bg-ap-bg/60"
    >
      <span className="text-sm">{label}</span>
      <span
        className={
          "relative h-5 w-9 flex-none rounded-full transition-colors " +
          (on ? "bg-ap-primary" : "bg-ap-line")
        }
      >
        <span
          className={
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all " +
            (on ? "start-[18px]" : "start-0.5")
          }
        />
      </span>
    </button>
  );
}

function Slider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}): ReactNode {
  return (
    <div className="px-2.5 py-1.5">
      <div className="mb-1 flex justify-between text-xs text-ap-muted">
        <span>{label}</span>
        <b>{Math.round(value * 100)}%</b>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(value * 100)}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        aria-label={label}
        className="w-full accent-ap-primary"
      />
    </div>
  );
}
