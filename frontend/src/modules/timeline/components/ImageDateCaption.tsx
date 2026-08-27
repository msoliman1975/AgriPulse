// The date of the picture on the map.
//
// This replaces a header badge that was wrong in both of its states. It
// only appeared when the drawn pass was OLDER than the scrubber's day, so
// on the days that actually had their own image — the ones a reader most
// wants confirmed — it showed nothing at all, and the caption blinked out
// every time the replay crossed an acquisition. Its other state replaced
// the date with a sentence about there being no image, so the one piece of
// text on the map changed shape as well as value.
//
// So: the caption is always the image's own date, and nothing else. It
// changes only when the pass changes, which is roughly once every five
// frames, and it fades in rather than cutting, so a replay reads as one
// continuous show rather than a stack of slides.
//
// The scrubber already says which day the play head is on, and says which
// days were real acquisitions. Repeating either here would make the reader
// compare two dates on one screen to learn a thing the fade already tells
// them: when this number does not move, the picture has not changed.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";

interface Props {
  /** The acquisition day of the drawn pass, or null when there is none. */
  imageDay: string | null;
  formatDay: (day: string) => string;
}

export function ImageDateCaption({ imageDay, formatDay }: Props): ReactNode {
  const { t } = useTranslation("timeline");

  return (
    <Card
      noPadding
      // `start-3`, so the caption mirrors with the script — and `bottom-8`
      // rather than `bottom-3`, because MapLibre's attribution control sits
      // at the bottom of the canvas and does NOT mirror: its positions are
      // physical. Under Arabic the caption moves to the bottom-right, which
      // is where the attribution already is. Clearing it vertically works in
      // both directions, and is what the Farm Console's map overlays do.
      className="pointer-events-none absolute bottom-8 start-3 z-10 bg-ap-panel/90 px-3 py-1.5"
      // The value changes under playback without the element being
      // focused, so it is announced politely rather than not at all.
      aria-live="polite"
      // The rail's own heading is the FRAME's date, and on an acquisition
      // day the two read the same. A test that matched on the text alone
      // could not tell which of them it had found.
      data-testid="timeline-image-date"
    >
      <span
        // Keyed on the day, so React replaces the node and the keyframe
        // runs again. A key of "none" is a value like any other, which is
        // what stops the pre-first-pass state flickering per frame.
        key={imageDay ?? "none"}
        className={
          "tl-date-fade block text-sm font-semibold tabular-nums " +
          (imageDay ? "text-ap-ink" : "text-ap-muted")
        }
      >
        {imageDay ? formatDay(imageDay) : t("caption.noImageYet")}
      </span>
    </Card>
  );
}
