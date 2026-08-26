// Slim "view bar" for /labs/map. The AgriPulse brand, tenant and farm
// switcher live in the app shell Header — this page follows that context.
// Page controls only: Index · Layers ▾ · Signals ▾ · + Add ▾ · ⚙.
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { INDEX_META, isThermalIndex } from "./constants";
import { MarkerLegend } from "../map/MarkerLegend";
import { Popover, PopHeading, PopItem, PopDivider } from "./ui";

export interface LayerState {
  aoi: boolean;
  blocks: boolean;
  borders: boolean;
  labels: boolean;
  borderOpacity: number;
  fillOpacity: number;
  // Field flags. ON by default: a layer nobody knows about is a layer nobody
  // uses, and the whole point of a flag is that somebody sees it.
  flags: boolean;
  // Closed flags keep their pin for the rest of its lifetime, so a farm
  // working through a season accumulates finished pins. This is the one
  // checkbox that clears them without hiding the layer.
  flagsOpenOnly: boolean;
  // Signal observations. The map draws every signal type at once now, so the
  // picker below narrows the layer rather than revealing it, and this is what
  // turns it off. Without it, "no signal picked" was the only off switch and
  // that made the layer invisible until somebody guessed the right type.
  signals: boolean;
}

interface Props {
  activeIndex: ApiIndexCode;
  onIndexChange: (c: ApiIndexCode) => void;
  /**
   * Which indices this console can actually draw, in menu order.
   *
   * Required rather than defaulted to the full list, because the two consoles
   * genuinely differ and a default would silently give the wrong one to
   * whichever caller forgot. The live console renders indices as sub-block
   * grid cells, which do not exist for the thermal product; the pixel console
   * renders the index COG, which does. See `constants.ts`.
   */
  indexOptions: ApiIndexCode[];
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
  /**
   * Whether to draw the `Layers ▾` chip and its popover.
   *
   * Farm Console v2 sets it false: it puts the same switches on the map as
   * picture cards, and two front doors onto one piece of state is how a
   * control ends up on only one of them. The live console has no cards, so it
   * keeps the chip and this defaults to true.
   */
  showLayersMenu?: boolean;
  onOpenSettings: () => void;
  showGrid: boolean;
  onToggleGrid: () => void;
  signalDefs: { id: string; name: string }[];
  signalDefId: string | null;
  onSignalDefChange: (id: string | null) => void;
  onAddBlock: () => void;
  onAddPivot: () => void;
  onAutoBlock: () => void;
  onBulkUpload: () => void;
  // Tenant-level create: a new farm, not a unit inside this one. Undefined
  // when the user lacks farm.create, which hides the menu entry entirely.
  onAddFarm?: () => void;
  /**
   * Optional slots either side of the page controls, so a caller can add
   * chrome without forking this component. Farm Console v2 puts its farm
   * identity strip in `leading`; the live console passes neither and renders
   * exactly as before.
   */
  leading?: ReactNode;
  trailing?: ReactNode;
}

function Chip({
  innerRef,
  onClick,
  children,
  primary,
  title,
  active,
}: {
  innerRef?: React.RefObject<HTMLButtonElement>;
  onClick?: () => void;
  children: ReactNode;
  primary?: boolean;
  title?: string;
  active?: boolean;
}): ReactNode {
  return (
    <button
      ref={innerRef}
      type="button"
      onClick={onClick}
      title={title}
      className={
        "inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-lg px-3 text-sm font-semibold transition-colors " +
        (primary
          ? "bg-ap-primary text-white hover:bg-ap-primary/90"
          : active
            ? "border border-ap-primary bg-ap-primary-soft text-ap-primary"
            : "border border-ap-line bg-ap-panel text-ap-ink hover:bg-ap-primary-soft")
      }
    >
      {children}
    </button>
  );
}

export function ViewBar({
  activeIndex,
  onIndexChange,
  indexOptions,
  layers,
  onLayersChange,
  showLayersMenu = true,
  onOpenSettings,
  showGrid,
  onToggleGrid,
  signalDefs,
  signalDefId,
  onSignalDefChange,
  onAddBlock,
  onAddPivot,
  onAutoBlock,
  onBulkUpload,
  onAddFarm,
  leading,
  trailing,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const indexRef = useRef<HTMLButtonElement>(null);
  const layersRef = useRef<HTMLButtonElement>(null);
  const signalsRef = useRef<HTMLButtonElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState<null | "index" | "layers" | "signals" | "add">(null);
  const close = () => setOpen(null);
  // Where the optical run ends, or -1 on a console that offers no thermal
  // index at all — in which case no heading is ever rendered. Found rather
  // than hardcoded to a count, so adding an optical index cannot leave the
  // thermal heading sitting one row too high.
  const firstThermal = indexOptions.findIndex(isThermalIndex);
  const activeSignalName = signalDefs.find((d) => d.id === signalDefId)?.name ?? null;

  return (
    <header className="relative z-30 flex h-12 flex-none items-center gap-2.5 border-b border-ap-line bg-ap-panel px-3.5">
      {leading}
      <Chip innerRef={indexRef} onClick={() => setOpen(open === "index" ? null : "index")}>
        🎨 {t("viewbar.index")}: <b>{INDEX_META[activeIndex].label}</b> ▾
      </Chip>
      {showLayersMenu ? (
        <Chip
          innerRef={layersRef}
          onClick={() => setOpen(open === "layers" ? null : "layers")}
          active={showGrid}
        >
          ▥ {t("viewbar.layers")} ▾
        </Chip>
      ) : null}
      <Chip
        innerRef={signalsRef}
        onClick={() => setOpen(open === "signals" ? null : "signals")}
        active={layers.signals}
      >
        ◇ {activeSignalName ?? t("layers.signals")} ▾
      </Chip>

      {trailing}

      <div className="flex-1" />

      <Chip innerRef={addRef} primary onClick={() => setOpen(open === "add" ? null : "add")}>
        ＋ {t("viewbar.add")} ▾
      </Chip>
      <Chip onClick={onOpenSettings} title={t("viewbar.settings")}>
        ⚙
      </Chip>

      {/* Index selector — drives the map pixel layer, the grid overlay and the
          inspector's featured card.

          The thermal three are separated by a heading of their own rather than
          listed on after MSI. They come from another satellite at a tenth the
          resolution, and a flat list says the opposite: that picking LST after
          NDVI changes only which number is drawn. The heading is the cheapest
          place to say "different sensor" once, instead of on every row or —
          the alternative that was live until now — nowhere at all. */}
      <Popover open={open === "index"} onClose={close} anchorRef={indexRef}>
        <PopHeading>{t("viewbar.vegIndex")}</PopHeading>
        {indexOptions.map((code, i) => (
          <span key={code} className="contents">
            {i === firstThermal ? (
              <>
                <PopDivider />
                <PopHeading>{t("viewbar.thermalIndex")}</PopHeading>
              </>
            ) : null}
            <PopItem
              icon={code === activeIndex ? "✓" : ""}
              onClick={() => {
                close();
                onIndexChange(code);
              }}
              hint={t(`dock.family.${INDEX_META[code].family}`)}
            >
              {INDEX_META[code].label}
            </PopItem>
          </span>
        ))}
      </Popover>

      {/* Layers popover — visibility, opacity + sub-block grid toggle */}
      <Popover open={showLayersMenu && open === "layers"} onClose={close} anchorRef={layersRef}>
        <PopHeading>{t("viewbar.mapLayers")}</PopHeading>
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
        <PopDivider />
        <Toggle
          label={`⚑ ${t("layers.flags")}`}
          on={layers.flags}
          onClick={() => onLayersChange({ flags: !layers.flags })}
        />
        {/* Nested under the layer it filters, and inert while that layer is
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
        <PopDivider />
        <Toggle label={`◫ ${t("layers.grid")}`} on={showGrid} onClick={onToggleGrid} />
        <div className="px-2.5 pb-1 pt-0.5 text-xs text-ap-muted">
          {t("layers.gridUsesIndex", { code: INDEX_META[activeIndex].label })}
        </div>
        <PopDivider />
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
        {/* The legend lives here rather than behind its own chip: this is
            already the menu holding the switches for the very layers it
            explains, so somebody asking "what is that mark" and somebody
            asking "how do I turn it off" end up in the same place. */}
        <PopDivider />
        <MarkerLegend />
      </Popover>

      {/* Signals popover — pick a signal to overlay its observations */}
      <Popover open={open === "signals"} onClose={close} anchorRef={signalsRef}>
        <PopHeading>{t("layers.signals")}</PopHeading>
        {/* Top item shows everything. It used to hide everything, which is
            why nobody saw an observation without first guessing which signal
            somebody had recorded. */}
        <PopItem
          icon={signalDefId == null ? "✓" : ""}
          onClick={() => {
            close();
            onSignalDefChange(null);
          }}
        >
          {t("layers.signalsAll")}
        </PopItem>
        {signalDefs.map((d) => (
          <PopItem
            key={d.id}
            icon={d.id === signalDefId ? "✓" : ""}
            onClick={() => {
              close();
              onSignalDefChange(d.id);
            }}
          >
            {d.name}
          </PopItem>
        ))}
      </Popover>

      {/* Add menu — native in-console create flows (draw on the map). Farm
          sits in its own group: it creates a sibling of this farm, not a unit
          inside it. */}
      <Popover open={open === "add"} onClose={close} anchorRef={addRef} align="end">
        {onAddFarm ? (
          <>
            <PopHeading>{t("viewbar.addNew")}</PopHeading>
            <PopItem
              icon="🌾"
              onClick={() => {
                close();
                onAddFarm();
              }}
              hint={t("add.viaDrawOrUpload")}
            >
              {t("add.farm")}
            </PopItem>
            <PopDivider />
          </>
        ) : null}
        <PopHeading>{t("viewbar.addToFarm")}</PopHeading>
        <PopItem
          icon="▦"
          onClick={() => {
            close();
            onAddBlock();
          }}
          hint={t("add.viaDraw")}
        >
          {t("add.block")}
        </PopItem>
        <PopItem
          icon="◎"
          onClick={() => {
            close();
            onAddPivot();
          }}
          hint={t("add.viaDraw")}
        >
          {t("add.pivot")}
        </PopItem>
        <PopItem
          icon="▩"
          onClick={() => {
            close();
            onAutoBlock();
          }}
          hint={t("add.viaGrid")}
        >
          {t("add.autoGrid")}
        </PopItem>
        <PopDivider />
        <PopItem
          icon="⬆"
          onClick={() => {
            close();
            onBulkUpload();
          }}
          hint={t("add.viaUpload")}
        >
          {t("add.bulkUpload")}
        </PopItem>
      </Popover>
    </header>
  );
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
      className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 hover:bg-ap-bg/60"
    >
      <span className="text-sm">{label}</span>
      <span
        className={
          "relative h-5 w-9 rounded-full transition-colors " + (on ? "bg-ap-primary" : "bg-ap-line")
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
        className="w-full accent-ap-primary"
      />
    </div>
  );
}
