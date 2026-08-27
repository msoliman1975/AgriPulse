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
      // Physically top-right, and deliberately NOT a logical `start`/`end`.
      //
      // The map's own furniture does not mirror — MapLibre's control
      // positions are physical — so a caption that mirrors will collide
      // with one of them in one of the two directions. The zoom buttons are
      // top-left and the attribution is along the bottom, which leaves
      // top-right free in both directions and at every width.
      //
      // The bottom is not an option at any offset. The attribution's height
      // depends on the viewport: at desktop widths the Esri string is one
      // line and the control occupies 10-34px above the canvas edge, but it
      // wraps to two lines on a narrow map and occupies about 44px. Below
      // `lg` the event rail is hidden and the map takes the full width, so a
      // phone hits the wrapped case. Any fixed `bottom-*` is right on one
      // side of that and wrong on the other.
      //
      // Nor is bottom-LEFT, which looks free: the attribution bar is
      // floated right inside a full-width container, so once it wraps it
      // spans most of a narrow map's bottom edge rather than staying in its
      // corner.
      className="pointer-events-none absolute right-3 top-3 z-10 bg-ap-panel/90 px-3 py-1.5"
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
