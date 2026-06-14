// Slim "view bar" for /labs/map-next. Collapses the legacy ~22-control
// toolbar to five always-visible controls: Farm switcher · Index ·
// Layers ▾ · + Add ▾ · ⚙ Settings. See the redesign proposal.
import { useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

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

interface Farm {
  id: string;
  name: string;
}

interface Props {
  farms: Farm[];
  farmId: string;
  farmName: string;
  onSwitchFarm: (id: string) => void;
  activeIndex: IndexCode;
  onIndexChange: (c: IndexCode) => void;
  layers: LayerState;
  onLayersChange: (patch: Partial<LayerState>) => void;
  onOpenSettings: () => void;
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
  farms,
  farmId,
  farmName,
  onSwitchFarm,
  activeIndex,
  onIndexChange,
  layers,
  onLayersChange,
  onOpenSettings,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const farmRef = useRef<HTMLButtonElement>(null);
  const indexRef = useRef<HTMLButtonElement>(null);
  const layersRef = useRef<HTMLButtonElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState<null | "farm" | "index" | "layers" | "add">(null);
  const close = () => setOpen(null);

  return (
    <header className="relative z-40 flex h-[54px] flex-none items-center gap-2.5 border-b border-ap-line bg-ap-panel px-3.5">
      <div className="me-1 flex items-center gap-2 font-bold tracking-tight">
        <span className="grid h-[22px] w-[22px] place-items-center rounded-md bg-ap-primary text-[13px] text-white">▲</span>
        <span className="text-ap-primary">Agri</span>
        <span className="-ms-2 text-ap-good">Pulse</span>
      </div>
      <span className="h-6 w-px bg-ap-line" />

      <Chip innerRef={farmRef} onClick={() => setOpen(open === "farm" ? null : "farm")}>
        🌾 {farmName} ▾
      </Chip>
      <Chip innerRef={indexRef} onClick={() => setOpen(open === "index" ? null : "index")}>
        🎨 {t("viewbar.index")}: <b>{INDEX_META[activeIndex].label}</b> ▾
      </Chip>
      <Chip innerRef={layersRef} onClick={() => setOpen(open === "layers" ? null : "layers")}>
        ▥ {t("viewbar.layers")} ▾
      </Chip>

      <div className="flex-1" />

      <Chip innerRef={addRef} primary onClick={() => setOpen(open === "add" ? null : "add")}>
        ＋ {t("viewbar.add")} ▾
      </Chip>
      <Chip onClick={onOpenSettings} title={t("viewbar.settings")}>
        ⚙
      </Chip>

      {/* Farm switcher */}
      <Popover open={open === "farm"} onClose={close} anchorRef={farmRef}>
        <PopHeading>{t("viewbar.switchFarm")}</PopHeading>
        {farms.map((f) => (
          <PopItem
            key={f.id}
            icon="🌾"
            onClick={() => {
              close();
              if (f.id !== farmId) onSwitchFarm(f.id);
            }}
          >
            {f.name}
          </PopItem>
        ))}
        <PopDivider />
        <PopItem
          icon="＋"
          onClick={() => {
            close();
            navigate("/farms/new");
          }}
        >
          {t("viewbar.newFarm")}
        </PopItem>
      </Popover>

      {/* Index selector (the 3 real block indices) */}
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

      {/* Layers popover — absorbs the legacy visibility + opacity toolbar */}
      <Popover open={open === "layers"} onClose={close} anchorRef={layersRef}>
        <PopHeading>{t("viewbar.mapLayers")}</PopHeading>
        <Toggle label={`🟦 ${t("layers.aoi")}`} on={layers.aoi} onClick={() => onLayersChange({ aoi: !layers.aoi })} />
        <Toggle label={`▦ ${t("layers.blocks")}`} on={layers.blocks} onClick={() => onLayersChange({ blocks: !layers.blocks })} />
        <Toggle label={`▢ ${t("layers.borders")}`} on={layers.borders} onClick={() => onLayersChange({ borders: !layers.borders })} />
        <Toggle label={`🅰 ${t("layers.labels")}`} on={layers.labels} onClick={() => onLayersChange({ labels: !layers.labels })} />
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
        <div className="px-2.5 pb-1 text-[11px] text-ap-muted">{t("layers.overlaysNote")}</div>
      </Popover>

      {/* Add menu — create flows delegate to existing routes for v1 */}
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
      <span
        className={"relative h-5 w-9 rounded-full transition-colors " + (on ? "bg-ap-primary" : "bg-ap-line")}
      >
        <span
          className={"absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all " + (on ? "start-[18px]" : "start-0.5")}
        />
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
