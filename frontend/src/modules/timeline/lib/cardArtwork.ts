// The carded datapoints' artwork, as data URLs.
//
// The six carded marks are DOM nodes, so they cannot use the images
// registered on the map — those live in MapLibre's own registry. They use
// the SAME canvas drawings through the preview functions the legend
// already uses, so the dock, the legend and the map can never disagree
// about what an alert chip looks like.
//
// Cached by image id. Each drawing is a canvas round-trip plus a PNG
// encode, and there are at most 31 distinct ones; redoing them per frame
// at playback speed would be the most expensive thing on the screen.

import type { TimelineEvent } from "@/api/timeline";
import {
  alertActionGlyph,
  alertChipPreview,
  flagPreview,
  markerSeverity,
  SEVERITY_COLOR,
  signalPreview,
  SIGNAL_MARKER_COLOR,
} from "@/modules/labs/map/markerIcons";
import { markerIconFor } from "./marks";

const cache = new Map<string, string | null>();

/**
 * The datapoint's glyph, or null when it has none.
 *
 * Null for a stage change, a completed activity and a recommendation:
 * those belong to a block rather than to a spot in it, and the dock draws
 * them as a numbered ring at the block's anchor instead of as a pin.
 */
export function cardIconUrl(event: TimelineEvent): string | null {
  const id = markerIconFor(event);
  if (id === null) return null;
  const hit = cache.get(id);
  if (hit !== undefined) return hit;

  const severity = markerSeverity(event.severity);
  let url: string | null = null;
  switch (event.kind) {
    case "alert":
      url = alertChipPreview(alertActionGlyph(event.code), severity);
      break;
    case "flag":
      url = flagPreview(severity, true);
      break;
    case "signal":
    case "visit":
      url = signalPreview(false);
      break;
    default:
      url = null;
  }
  cache.set(id, url);
  return url;
}

/**
 * The number badge's colour.
 *
 * The same rule the artwork follows: severity for a thing somebody judged,
 * slate for an observation, which is a measurement and carries no verdict.
 * A green badge on the slate diamond would be the map saying "this reading
 * is fine", which nobody has decided.
 */
export function badgeColor(kind: string, severity: string | null | undefined): string {
  if (kind === "signal" || kind === "visit") return SIGNAL_MARKER_COLOR;
  return SEVERITY_COLOR[markerSeverity(severity)];
}
