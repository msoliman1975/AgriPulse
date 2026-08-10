// Slim "view bar" for /labs/map. The AgriPulse brand, tenant and farm
// switcher live in the app shell Header — this page follows that context.
// Page controls only: Index · Layers ▾ · Signals ▾ · + Add ▾ · ⚙.
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { INDEX_META, MAP_INDEX_ORDER } from "./constants";
import { Popover, PopHeading, PopItem, PopDivider } from "./ui";

export interface LayerState {
  aoi: boolean;
  blocks: boolean;
  borders: boolean;
  labels: boolean;
  borderOpacity: number;
  fillOpacity: number;
}

interface Props {
  activeIndex: ApiIndexCode;
  onIndexChange: (c: ApiIndexCode) => void;
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
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
  layers,
  onLayersChange,
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
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const indexRef = useRef<HTMLButtonElement>(null);
  const layersRef = useRef<HTMLButtonElement>(null);
  const signalsRef = useRef<HTMLButtonElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState<null | "index" | "layers" | "signals" | "add">(null);
  const close = () => setOpen(null);
  const activeSignalName = signalDefs.find((d) => d.id === signalDefId)?.name ?? null;

  return (
    <header className="relative z-30 flex h-12 flex-none items-center gap-2.5 border-b border-ap-line bg-ap-panel px-3.5">
      <Chip innerRef={indexRef} onClick={() => setOpen(open === "index" ? null : "index")}>
        🎨 {t("viewbar.index")}: <b>{INDEX_META[activeIndex].label}</b> ▾
      </Chip>
      <Chip
        innerRef={layersRef}
        onClick={() => setOpen(open === "layers" ? null : "layers")}
        active={showGrid}
      >
        ▥ {t("viewbar.layers")} ▾
      </Chip>
      <Chip
        innerRef={signalsRef}
        onClick={() => setOpen(open === "signals" ? null : "signals")}
        active={Boolean(signalDefId)}
      >
        📡 {activeSignalName ?? t("layers.signals")} ▾
      </Chip>

      <div className="flex-1" />

      <Chip innerRef={addRef} primary onClick={() => setOpen(open === "add" ? null : "add")}>
        ＋ {t("viewbar.add")} ▾
      </Chip>
      <Chip onClick={onOpenSettings} title={t("viewbar.settings")}>
        ⚙
      </Chip>

      {/* Index selector — drives the map grid overlay + the inspector featured */}
      <Popover open={open === "index"} onClose={close} anchorRef={indexRef}>
        <PopHeading>{t("viewbar.vegIndex")}</PopHeading>
        {MAP_INDEX_ORDER.map((code) => (
          <PopItem
            key={code}
            icon={code === activeIndex ? "✓" : ""}
            onClick={() => {
              close();
              onIndexChange(code);
            }}
            hint={t(`dock.family.${INDEX_META[code].family}`)}
          >
            {INDEX_META[code].label}
          </PopItem>
        ))}
      </Popover>

      {/* Layers popover — visibility, opacity + sub-block grid toggle */}
      <Popover open={open === "layers"} onClose={close} anchorRef={layersRef}>
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
      </Popover>

      {/* Signals popover — pick a signal to overlay its observations */}
      <Popover open={open === "signals"} onClose={close} anchorRef={signalsRef}>
        <PopHeading>{t("layers.signals")}</PopHeading>
        <PopItem
          icon={signalDefId == null ? "✓" : ""}
          onClick={() => {
            close();
            onSignalDefChange(null);
          }}
        >
          {t("layers.signalsNone")}
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
