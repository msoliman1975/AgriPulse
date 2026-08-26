// The map's own tool rail — "how am I reading this", as opposed to the view
// bar's "what am I looking at".
//
// Vertical, on the map's trailing edge. Tools sit apart from layers, which
// are picture cards in the opposite corner (MapLayersControl): a tool changes
// how the map is READ — anomaly, contrast, two dates side by side — where a
// layer only decides what is drawn. Mixing the two in one menu is what the
// old `Layers ▾` popover did, and it is why the mesh toggle was buried nine
// rows down among visibility switches it has nothing to do with.
//
// Pixels and the mesh appear in BOTH places on purpose. They are the two
// controls an operator reaches for constantly, they are legitimately layers
// AND view modes, and one shared piece of state drives both — so the rail and
// the cards can never disagree about which is on.
//
// Controls that Slice 3 will implement are rendered DISABLED with a reason
// rather than hidden. A greyed control with an explanation tells the reader
// the capability is coming; a missing one tells them nothing.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";

interface Props {
  showPixels: boolean;
  onTogglePixels: () => void;
  /** Blocks with an index raster for the selected scene. Zero disables. */
  pixelsAvailable: boolean;
  showGrid: boolean;
  onToggleGrid: () => void;
  gridAvailable: boolean;
  /**
   * The farm HAS sub-block zoning, but the index being drawn cannot use it —
   * true only for the thermal indices, whose product has no grid config and
   * therefore no cells. A separate flag from `gridAvailable` because the two
   * need different hints: "this farm has no zones" sends the reader to grid
   * configuration, which would not help here.
   */
  gridUnavailableForIndex?: boolean;
  onFullscreen: () => void;
  isFullscreen: boolean;
  className?: string;
}

interface DockButton {
  key: string;
  glyph: string;
  on?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  /** i18n key under `mapDock.` for the accessible name. */
  labelKey: string;
  /** i18n key under `mapDock.` for the "why is this off" hint. */
  hintKey?: string;
}

export function MapDock({
  showPixels,
  onTogglePixels,
  pixelsAvailable,
  showGrid,
  onToggleGrid,
  gridAvailable,
  gridUnavailableForIndex = false,
  onFullscreen,
  isFullscreen,
  className,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");

  const buttons: DockButton[] = [
    // Pixels first: they are the reading, and the mesh is drawn over them.
    {
      key: "pixels",
      glyph: "▦",
      on: showPixels,
      disabled: !pixelsAvailable,
      onClick: onTogglePixels,
      labelKey: "pixels",
      hintKey: pixelsAvailable ? undefined : "pixelsUnavailable",
    },
    {
      key: "grid",
      glyph: "⌗",
      on: showGrid && !gridUnavailableForIndex,
      disabled: !gridAvailable || gridUnavailableForIndex,
      onClick: onToggleGrid,
      labelKey: "grid",
      hintKey: gridUnavailableForIndex
        ? "gridNotForThisIndex"
        : gridAvailable
          ? undefined
          : "gridUnavailable",
    },
    { key: "anomaly", glyph: "◔", disabled: true, labelKey: "anomaly", hintKey: "comingSoon" },
    { key: "contrast", glyph: "◐", disabled: true, labelKey: "contrast", hintKey: "comingSoon" },
    { key: "compare", glyph: "⇹", disabled: true, labelKey: "compare", hintKey: "comingSoon" },
    {
      key: "fullscreen",
      glyph: isFullscreen ? "⛶" : "⛶",
      on: isFullscreen,
      onClick: onFullscreen,
      labelKey: isFullscreen ? "exitFullscreen" : "fullscreen",
    },
  ];

  return (
    <Card className={className} noPadding>
      <div className="flex flex-col items-center gap-1 p-1">
        {buttons.map((b) => {
          const label = t(`mapDock.${b.labelKey}`);
          const hint = b.hintKey ? t(`mapDock.${b.hintKey}`) : null;
          return (
            <button
              key={b.key}
              type="button"
              onClick={b.onClick}
              disabled={b.disabled}
              aria-pressed={b.on ?? undefined}
              aria-label={label}
              title={hint ? `${label} — ${hint}` : label}
              className={
                "grid h-7 w-7 place-items-center rounded-md border text-sm transition-colors " +
                (b.disabled
                  ? "cursor-not-allowed border-transparent text-ap-muted/40"
                  : b.on
                    ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
                    : "border-transparent text-ap-muted hover:bg-ap-bg hover:text-ap-ink")
              }
            >
              <span aria-hidden="true">{b.glyph}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
