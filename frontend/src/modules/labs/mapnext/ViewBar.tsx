// Slim "view bar" for /labs/map-next. The AgriPulse brand, tenant and farm
// switcher live in the app shell Header (src/shell/Header.tsx) — this page
// follows that farm context, so the bar carries ONLY page controls:
// Index · Layers ▾ · + Add ▾ · ⚙ Settings.
import { useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { IndexCode } from "../map/types";
import { INDEX_META, INDEX_ORDER } from "./constants";
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
  farmId: string;
  activeIndex: IndexCode;
  onIndexChange: (c: IndexCode) => void;
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
  onOpenSettings: () => void;
  // Sub-block grid overlay controls.
  showGrid: boolean;
  onToggleGrid: () => void;
  gridIndex: ApiIndexCode;
  onGridIndexChange: (c: ApiIndexCode) => void;
  gridIndexOptions: ApiIndexCode[];
}

function Chip({
  innerRef,
  onClick,
  children,
  primary,
  title,
}: {
  innerRef?: React.RefObject<HTMLButtonElement>;
  onClick?: () => void;
  children: ReactNode;
  primary?: boolean;
  title?: string;
}): ReactNode {
  return (
    <button
      ref={innerRef}
      type="button"
      onClick={onClick}
      title={title}
      className={
        "inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-lg px-3 text-[13px] font-semibold transition-colors " +
        (primary
          ? "bg-ap-primary text-white hover:bg-ap-primary/90"
          : "border border-ap-line bg-ap-panel text-ap-ink hover:bg-ap-primary-soft")
      }
    >
      {children}
    </button>
  );
}

export function ViewBar({
  farmId,
  activeIndex,
  onIndexChange,
  layers,
  onLayersChange,
  onOpenSettings,
  showGrid,
  onToggleGrid,
  gridIndex,
  onGridIndexChange,
  gridIndexOptions,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const indexRef = useRef<HTMLButtonElement>(null);
  const layersRef = useRef<HTMLButtonElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState<null | "index" | "layers" | "add">(null);
  const close = () => setOpen(null);

  return (
    <header className="relative z-30 flex h-12 flex-none items-center gap-2.5 border-b border-ap-line bg-ap-panel px-3.5">
      <Chip innerRef={indexRef} onClick={() => setOpen(open === "index" ? null : "index")}>
        🎨 {t("viewbar.index")}: <b>{INDEX_META[activeIndex].label}</b> ▾
      </Chip>
      <Chip innerRef={layersRef} onClick={() => setOpen(open === "layers" ? null : "layers")}>
        ▥ {t("viewbar.layers")} {showGrid ? "•" : ""} ▾
      </Chip>

      <div className="flex-1" />

      <Chip innerRef={addRef} primary onClick={() => setOpen(open === "add" ? null : "add")}>
        ＋ {t("viewbar.add")} ▾
      </Chip>
      <Chip onClick={onOpenSettings} title={t("viewbar.settings")}>
        ⚙
      </Chip>

      {/* Index selector — the inspector's featured block index (3 real codes) */}
      <Popover open={open === "index"} onClose={close} anchorRef={indexRef}>
        <PopHeading>{t("viewbar.vegIndex")}</PopHeading>
        {INDEX_ORDER.map((code) => (
          <PopItem
            key={code}
            icon={code === activeIndex ? "✓" : ""}
            onClick={() => {
              close();
              onIndexChange(code);
            }}
            hint={INDEX_META[code].family}
          >
            {INDEX_META[code].label}
          </PopItem>
        ))}
      </Popover>

      {/* Layers popover — visibility, opacity + sub-block grid overlay */}
      <Popover open={open === "layers"} onClose={close} anchorRef={layersRef}>
        <PopHeading>{t("viewbar.mapLayers")}</PopHeading>
        <Toggle label={`🟦 ${t("layers.aoi")}`} on={layers.aoi} onClick={() => onLayersChange({ aoi: !layers.aoi })} />
        <Toggle label={`▦ ${t("layers.blocks")}`} on={layers.blocks} onClick={() => onLayersChange({ blocks: !layers.blocks })} />
        <Toggle label={`▢ ${t("layers.borders")}`} on={layers.borders} onClick={() => onLayersChange({ borders: !layers.borders })} />
        <Toggle label={`🅰 ${t("layers.labels")}`} on={layers.labels} onClick={() => onLayersChange({ labels: !layers.labels })} />
        <PopDivider />
        <PopHeading>{t("layers.overlays")}</PopHeading>
        <Toggle label={`◫ ${t("layers.grid")}`} on={showGrid} onClick={onToggleGrid} />
        {showGrid ? (
          <div className="flex items-center gap-2 px-2.5 py-1.5">
            <span className="text-[12px] text-ap-muted">{t("layers.gridIndex")}</span>
            <select
              value={gridIndex}
              onChange={(e) => onGridIndexChange(e.target.value as ApiIndexCode)}
              className="flex-1 rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-[13px] text-ap-ink"
            >
              {gridIndexOptions.map((c) => (
                <option key={c} value={c}>
                  {c.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        ) : null}
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
        <PopDivider />
        <div className="px-2.5 pb-1 text-[11px] text-ap-muted">{t("layers.signalNote")}</div>
      </Popover>

      {/* Add menu — create flows delegate to existing routes for now */}
      <Popover open={open === "add"} onClose={close} anchorRef={addRef} align="end">
        <PopHeading>{t("viewbar.addToFarm")}</PopHeading>
        <PopItem icon="▦" onClick={() => { close(); navigate(`/farms/${farmId}/blocks/new`); }} hint={t("add.viaForm")}>
          {t("add.block")}
        </PopItem>
        <PopItem icon="▩" onClick={() => { close(); navigate(`/farms/${farmId}/blocks/auto-grid`); }}>
          {t("add.autoGrid")}
        </PopItem>
        <PopItem icon="◎" onClick={() => { close(); navigate(`/labs/map/${farmId}`); }} hint={t("add.viaMap")}>
          {t("add.pivot")}
        </PopItem>
      </Popover>
    </header>
  );
}

function Toggle({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }): ReactNode {
  return (
    <button type="button" onClick={onClick} className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 hover:bg-ap-bg/60">
      <span className="text-[13px]">{label}</span>
      <span className={"relative h-5 w-9 rounded-full transition-colors " + (on ? "bg-ap-primary" : "bg-ap-line")}>
        <span className={"absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all " + (on ? "start-[18px]" : "start-0.5")} />
      </span>
    </button>
  );
}

function Slider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }): ReactNode {
  return (
    <div className="px-2.5 py-1.5">
      <div className="mb-1 flex justify-between text-[12px] text-ap-muted">
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
