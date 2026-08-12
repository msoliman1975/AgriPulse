// The map's own control cluster — "how am I reading this", as opposed to the
// view bar's "what am I looking at".
//
// The sub-block grid toggle moves here from the Layers popover on purpose: it
// is a view MODE, not a visibility flag. It changes what the colours mean,
// not merely whether something is drawn, which puts it with anomaly and
// contrast rather than with "show borders".
//
// Controls that Slice 3 will implement are rendered DISABLED with a reason
// rather than hidden. A greyed control with an explanation tells the reader
// the capability is coming; a missing one tells them nothing.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";

interface Props {
  showGrid: boolean;
  onToggleGrid: () => void;
  gridAvailable: boolean;
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
  showGrid,
  onToggleGrid,
  gridAvailable,
  onFullscreen,
  isFullscreen,
  className,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");

  const buttons: DockButton[] = [
    {
      key: "grid",
      glyph: "◫",
      on: showGrid,
      disabled: !gridAvailable,
      onClick: onToggleGrid,
      labelKey: "grid",
      hintKey: gridAvailable ? undefined : "gridUnavailable",
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
      <div className="flex items-center gap-1 p-1">
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
