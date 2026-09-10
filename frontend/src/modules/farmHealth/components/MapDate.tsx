// The day the map is showing, in the map's own corner.
//
// It used to sit at the far end of the control bar above the map, which
// meant the reader's eye had to leave the picture to learn what date the
// picture was. Mohamed asked on 2026-09-10 for the Farm Timeline's
// arrangement instead, and this is that component's twin — see
// `modules/timeline/components/ImageDateCaption.tsx` for the full reasoning
// behind the corner it picks.
//
// The short version: physically top-right and deliberately NOT a logical
// `end`. MapLibre's control positions are physical and do not mirror, so a
// caption that mirrors collides with the zoom buttons in one of the two
// directions. Top-left holds the zoom control, the bottom edge holds the
// attribution — whose height depends on whether the Esri string wraps — so
// top-right is the only corner free at every width in both directions.

import type { ReactNode } from "react";

import { Card } from "@/components/Card";

interface Props {
  /** The day on show, already formatted in the reader's language. */
  text: string;
  /** Changing this replays the fade. Pass the day, not the text. */
  dayKey: string | number;
}

export function MapDate({ text, dayKey }: Props): ReactNode {
  return (
    <Card
      noPadding
      className="pointer-events-none absolute right-3 top-3 z-10 bg-ap-panel/90 px-3 py-1.5"
      // The value changes under playback with nothing focused, so it is
      // announced politely rather than not at all.
      aria-live="polite"
      data-testid="farm-health-map-date"
    >
      <span
        // Keyed on the day, so React replaces the node and the fade runs
        // again. The keyframe is the Timeline's, defined once in index.css.
        key={dayKey}
        className="tl-date-fade block text-sm font-semibold tabular-nums text-ap-ink"
      >
        {text}
      </span>
    </Card>
  );
}
