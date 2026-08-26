// The map's datapoint control — one place that decides what DATA the map
// draws.
//
// Replaces two controls that split the same job between opposite corners of
// the map: a vertical tool rail on the trailing edge, and a strip of picture
// cards on the leading edge. Pixels and the mesh appeared in both, which
// meant two front doors onto one piece of state; the index selector was in
// the top bar, a third; and there was no switch at all for alert chips.
//
// What lives here is everything that answers "is this thing on the map":
// the index (its "None" is the pixel off switch), alert chips, field flags,
// signal readings, and the legend that says what those marks mean. What does
// NOT live here is the map's frame — farm and block borders, mesh lines,
// opacity, labels — which is on the top bar, because it is not data.
//
// Each row is a button with an active state, and the ones that need a choice
// open a panel beside the rail rather than on top of it, so the rail never
// moves under the pointer that just clicked it.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AnyIndexCode } from "@/api/indices";
import { Card } from "@/components/Card";
import { INDEX_META, isThermalIndex } from "../mapnext/constants";

/** Flags, as one tri-state rather than a switch plus a nested checkbox. */
export type FlagsMode = "current" | "historical" | "none";

interface Props {
  /** The index being drawn, or null when the reader picked "None". */
  activeIndex: AnyIndexCode | null;
  /** Which index the "None" row falls back FROM, for the row's caption. */
  indexOptions: AnyIndexCode[];
  onIndexChange: (code: AnyIndexCode | null) => void;
  /** Zero blocks carry an image for this date — every index row is inert. */
  pixelsAvailable: boolean;

  alerts: boolean;
  onAlertsChange: (on: boolean) => void;

  flagsMode: FlagsMode;
  onFlagsModeChange: (mode: FlagsMode) => void;

  /** null = every signal type; a definition id narrows to one. */
  signalDefs: { id: string; name: string }[];
  signalsOn: boolean;
  signalDefId: string | null;
  onSignalsChange: (next: { on: boolean; defId: string | null }) => void;

  markLegend: boolean;
  onMarkLegendChange: (on: boolean) => void;

  onFullscreen: () => void;
  isFullscreen: boolean;
  className?: string;
}

type PanelKey = "index" | "flags" | "signals";

export function MapDataControl({
  activeIndex,
  indexOptions,
  onIndexChange,
  pixelsAvailable,
  alerts,
  onAlertsChange,
  flagsMode,
  onFlagsModeChange,
  signalDefs,
  signalsOn,
  signalDefId,
  onSignalsChange,
  markLegend,
  onMarkLegendChange,
  onFullscreen,
  isFullscreen,
  className,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [open, setOpen] = useState<PanelKey | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on an outside click and on Escape. A panel that only closes via its
  // own button is one a reader leaves open over the map.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Where the optical run ends, so the thermal three get a heading of their
  // own. Found rather than counted: adding an optical index cannot then leave
  // the heading one row too high.
  const firstThermal = indexOptions.findIndex(isThermalIndex);

  const flagsLabel = t(`dataControl.flagsMode.${flagsMode}`);
  const signalLabel = !signalsOn
    ? t("dataControl.signalsNone")
    : signalDefId
      ? (signalDefs.find((d) => d.id === signalDefId)?.name ?? t("dataControl.signalsAll"))
      : t("dataControl.signalsAll");

  return (
    <div ref={rootRef} className={className}>
      <Card noPadding className="bg-ap-panel/95 shadow-card">
        <div className="flex flex-col items-stretch gap-0.5 p-1">
          <Row
            glyph="🎨"
            label={t("dataControl.index")}
            value={activeIndex ? INDEX_META[activeIndex].label : t("dataControl.indexNone")}
            on={activeIndex != null}
            disabled={!pixelsAvailable && activeIndex == null}
            hint={pixelsAvailable ? undefined : t("dataControl.indexUnavailable")}
            expanded={open === "index"}
            onClick={() => setOpen(open === "index" ? null : "index")}
          />
          <Row
            glyph="◆"
            label={t("dataControl.alerts")}
            value={alerts ? t("dataControl.on") : t("dataControl.off")}
            on={alerts}
            onClick={() => onAlertsChange(!alerts)}
          />
          <Row
            glyph="⚑"
            label={t("dataControl.flags")}
            value={flagsLabel}
            on={flagsMode !== "none"}
            expanded={open === "flags"}
            onClick={() => setOpen(open === "flags" ? null : "flags")}
          />
          <Row
            glyph="◇"
            label={t("dataControl.signals")}
            value={signalLabel}
            on={signalsOn}
            expanded={open === "signals"}
            onClick={() => setOpen(open === "signals" ? null : "signals")}
          />

          <span className="my-0.5 h-px bg-ap-line" aria-hidden="true" />

          <Row
            glyph="?"
            label={t("dataControl.markLegend")}
            value={markLegend ? t("dataControl.shown") : t("dataControl.hidden")}
            on={markLegend}
            onClick={() => onMarkLegendChange(!markLegend)}
          />
          <Row
            glyph="⛶"
            label={isFullscreen ? t("dataControl.exitFullscreen") : t("dataControl.fullscreen")}
            on={isFullscreen}
            onClick={onFullscreen}
          />
        </div>
      </Card>

      {/* Panels open toward the map's interior — `end-full` in logical terms,
          so RTL flips with the rest of the page and never off the canvas. */}
      {open === "index" ? (
        <Panel title={t("dataControl.indexTitle")}>
          <Choice
            label={t("dataControl.indexNone")}
            hint={t("dataControl.indexNoneHint")}
            selected={activeIndex == null}
            onClick={() => {
              setOpen(null);
              onIndexChange(null);
            }}
          />
          <Divider />
          {indexOptions.map((code, i) => (
            <span key={code} className="contents">
              {i === firstThermal ? (
                <>
                  <Divider />
                  <Heading>{t("viewbar.thermalIndex")}</Heading>
                </>
              ) : null}
              <Choice
                label={INDEX_META[code].label}
                hint={t(`dock.family.${INDEX_META[code].family}`)}
                selected={code === activeIndex}
                onClick={() => {
                  setOpen(null);
                  onIndexChange(code);
                }}
              />
            </span>
          ))}
        </Panel>
      ) : null}

      {open === "flags" ? (
        <Panel title={t("dataControl.flagsTitle")}>
          {(["current", "historical", "none"] as const).map((mode) => (
            <Choice
              key={mode}
              label={t(`dataControl.flagsMode.${mode}`)}
              hint={t(`dataControl.flagsHint.${mode}`)}
              selected={flagsMode === mode}
              onClick={() => {
                setOpen(null);
                onFlagsModeChange(mode);
              }}
            />
          ))}
        </Panel>
      ) : null}

      {open === "signals" ? (
        <Panel title={t("dataControl.signalsTitle")}>
          <Choice
            label={t("dataControl.signalsAll")}
            selected={signalsOn && signalDefId == null}
            onClick={() => {
              setOpen(null);
              onSignalsChange({ on: true, defId: null });
            }}
          />
          <Choice
            label={t("dataControl.signalsNone")}
            selected={!signalsOn}
            onClick={() => {
              setOpen(null);
              onSignalsChange({ on: false, defId: null });
            }}
          />
          {signalDefs.length > 0 ? <Divider /> : null}
          {signalDefs.map((d) => (
            <Choice
              key={d.id}
              label={d.name}
              selected={signalsOn && signalDefId === d.id}
              onClick={() => {
                setOpen(null);
                onSignalsChange({ on: true, defId: d.id });
              }}
            />
          ))}
        </Panel>
      ) : null}
    </div>
  );
}

/**
 * One rail row: glyph, name, and the state in words.
 *
 * The state is spelled out rather than left to the highlight. "Flags: Current"
 * and "Flags: Historical" are both ON, and a control that shows only on/off
 * cannot tell them apart without being opened.
 */
function Row({
  glyph,
  label,
  value,
  on,
  disabled,
  hint,
  expanded,
  onClick,
}: {
  glyph: string;
  label: string;
  value?: string;
  on?: boolean;
  disabled?: boolean;
  hint?: string;
  expanded?: boolean;
  onClick: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-pressed={disabled ? undefined : on}
      aria-expanded={expanded}
      title={hint ? `${label} — ${hint}` : value ? `${label}: ${value}` : label}
      className={
        "flex w-[132px] items-center gap-1.5 rounded-md border px-1.5 py-1 text-start transition-colors " +
        (disabled
          ? "cursor-not-allowed border-transparent text-ap-muted/40"
          : on
            ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
            : "border-transparent text-ap-muted hover:bg-ap-bg hover:text-ap-ink")
      }
    >
      <span aria-hidden="true" className="w-4 flex-none text-center text-sm">
        {glyph}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[11px] font-semibold leading-tight">{label}</span>
        {value ? (
          <span className="block truncate text-[10px] leading-tight opacity-80">{value}</span>
        ) : null}
      </span>
    </button>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }): ReactNode {
  return (
    <Card
      noPadding
      // Centred on the rail, not hung from its top. The rail itself sits at
      // the map's vertical middle, so a panel anchored at `top-0` and 70vh
      // tall runs off the bottom of the window — the thirteen-index list did
      // exactly that, and gave the whole page a scroll bar.
      className="absolute end-full top-1/2 me-2 max-h-[70vh] w-[212px] -translate-y-1/2 overflow-y-auto bg-ap-panel/98 p-1 shadow-card"
    >
      <Heading>{title}</Heading>
      {children}
    </Card>
  );
}

function Heading({ children }: { children: ReactNode }): ReactNode {
  return (
    <p className="px-2 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-wide text-ap-muted">
      {children}
    </p>
  );
}

function Divider(): ReactNode {
  return <div className="my-1 border-t border-ap-line" />;
}

function Choice({
  label,
  hint,
  selected,
  onClick,
}: {
  label: string;
  hint?: string;
  selected: boolean;
  onClick: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start hover:bg-ap-bg/60"
    >
      <span aria-hidden="true" className="w-3 flex-none text-xs text-ap-primary">
        {selected ? "✓" : ""}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-ap-ink">{label}</span>
        {hint ? <span className="block truncate text-[10px] text-ap-muted">{hint}</span> : null}
      </span>
    </button>
  );
}
