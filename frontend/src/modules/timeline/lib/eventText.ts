// The one place a datapoint's title is resolved.
//
// The rail and the dock both print it, and they must print the same
// string: a card and its rail row are the same thing seen twice, so a
// reader who cannot match them has lost the tie the numbers exist to give.

import type { TFunction } from "i18next";

import type { TimelineEvent } from "@/api/timeline";
import { markerSeverity } from "@/modules/labs/map/markerIcons";

/**
 * The datapoint's own text, or the best fallback.
 *
 * Never an empty string. A blank line reads as a rendering fault rather
 * than as a datapoint that carried no note, so the enum-ish code is the
 * next best thing and the kind's own label is the floor.
 */
export function eventTitle(
  event: TimelineEvent,
  t: TFunction<"timeline">,
  language: string,
): string {
  const own = language.startsWith("ar") ? (event.title_ar ?? event.title_en) : event.title_en;
  if (own) return own;
  if (event.code) {
    return t(`code.${event.kind}.${event.code}`, { defaultValue: event.code });
  }
  return t(`kind.${event.kind}`);
}

/**
 * Severity to the `<Pill>` kind. `Pill` carries ok / warn / crit.
 *
 * Shared for the same reason `eventTitle` is: the rail row and the dock
 * card are one datapoint drawn twice, and a card that reads "critical"
 * beside a row that reads "ok" is a bug the reader has to resolve.
 */
export function eventPillKind(event: TimelineEvent): "ok" | "warn" | "crit" {
  switch (markerSeverity(event.severity)) {
    case "critical":
      return "crit";
    case "watch":
      return "warn";
    default:
      return "ok";
  }
}
