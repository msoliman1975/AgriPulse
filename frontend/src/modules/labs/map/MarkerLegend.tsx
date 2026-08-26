// What the marks on the map mean.
//
// The map carries three unrelated things — an open alert, a flag somebody
// raised in the field, and a signal reading — and until now it drew all three
// as coloured circles with nothing on screen to tell them apart. Giving them
// three shapes is most of the fix; this is the rest of it, because a shape
// only reads as a word once somebody has been told which word.
//
// Every swatch here is drawn by the SAME functions that produce the map's
// marker images (markerIcons.ts), handed over as data URLs. A legend redrawn
// separately drifts from the map the first time a colour changes, and a
// legend that disagrees with the map is worse than no legend.

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  ALERT_ACTION_TYPES,
  alertChipPreview,
  flagPreview,
  signalPreview,
  type AlertActionType,
  type MarkerSeverity,
} from "./markerIcons";

// The three severities, worst first — the order they are read in.
const SEVERITIES: readonly MarkerSeverity[] = ["critical", "watch", "ok"];

// `no_action` is excluded on purpose: a decision-tree leaf can name it, but an
// alert that says "do nothing" is not something the map has ever opened, and
// listing it here would invite the question of where to find one.
const LEGEND_ACTIONS: readonly AlertActionType[] = ALERT_ACTION_TYPES.filter(
  (a) => a !== "no_action",
);

function Swatch({ src, alt }: { src: string | null; alt: string }) {
  // A null src means the canvas was unavailable (a test environment, a
  // browser with canvas disabled). Reserve the space rather than collapsing
  // the row, so the labels stay aligned with the rows that did draw.
  if (!src) return <span className="inline-block h-5 w-8" aria-hidden />;
  return <img src={src} alt={alt} className="inline-block h-5 w-auto align-middle" />;
}

export function MarkerLegend(): React.ReactNode {
  const { t } = useTranslation("farmConsole");

  // Drawn once. Each preview is a canvas round-trip, and there are a dozen of
  // them, so redrawing on every popover render would be visible.
  const art = useMemo(
    () => ({
      alerts: SEVERITIES.map((s) => ({
        severity: s,
        src: alertChipPreview("unknown", s),
      })),
      actions: LEGEND_ACTIONS.map((a) => ({
        action: a,
        // Rendered in the "watch" colour rather than one colour per row: this
        // block is about the PICTURE, and varying the colour too would imply
        // each verb has a severity of its own.
        src: alertChipPreview(a, "watch"),
      })),
      flags: SEVERITIES.map((s) => ({ severity: s, src: flagPreview(s, true) })),
      flagClosed: flagPreview("critical", false),
      signal: signalPreview(false),
      signalStack: signalPreview(true),
    }),
    [],
  );

  return (
    <div className="max-w-xs px-2.5 py-2 text-xs text-ap-fg">
      <div className="pb-1.5 font-medium">{t("markerLegend.title")}</div>

      <div className="pb-1 font-medium">{t("markerLegend.alerts")}</div>
      <p className="pb-1.5 text-ap-muted">{t("markerLegend.alertsHint")}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-2">
        {art.alerts.map(({ severity, src }) => (
          <span key={severity} className="flex items-center gap-1.5">
            <Swatch src={src} alt="" />
            <span>{t(`markerLegend.severity.${severity}`)}</span>
          </span>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 pb-2">
        {art.actions.map(({ action, src }) => (
          <span key={action} className="flex items-center gap-1.5">
            <Swatch src={src} alt="" />
            <span className="text-ap-muted">{t(`markerLegend.action.${action}`)}</span>
          </span>
        ))}
      </div>

      <div className="pb-1 font-medium">{t("markerLegend.flags")}</div>
      <p className="pb-1.5 text-ap-muted">{t("markerLegend.flagsHint")}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-2">
        {art.flags.map(({ severity, src }) => (
          <span key={severity} className="flex items-center gap-1.5">
            <Swatch src={src} alt="" />
            <span>{t(`markerLegend.severity.${severity}`)}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <Swatch src={art.flagClosed} alt="" />
          <span className="text-ap-muted">{t("flags.closed")}</span>
        </span>
      </div>

      <div className="pb-1 font-medium">{t("markerLegend.signals")}</div>
      <div className="flex items-center gap-1.5">
        <Swatch src={art.signal} alt="" />
        <span className="text-ap-muted">{t("markerLegend.signalsHint")}</span>
      </div>
      {/* A doubled outline, not a number: the mark must stay drawable when the
          style's glyph endpoint does not answer. */}
      <div className="flex items-center gap-1.5 pt-1">
        <Swatch src={art.signalStack} alt="" />
        <span className="text-ap-muted">{t("markerLegend.signalsStackHint")}</span>
      </div>
    </div>
  );
}
