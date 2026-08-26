// Turning timeline events into map marks.
//
// Three of the four shapes already exist — the chip (alert), the pennant
// (flag) and the diamond (signal observation) were drawn for the Farm
// Console and are registered by `registerMarkerImages`. This module only
// decides which event gets which image and where it stands; the artwork
// and the ids come from one place so a layer can never ask for an image
// nobody registered, which renders as nothing at all with no error.
//
// Pure, so it is unit-testable without a map.

import { pointOnFeature } from "@turf/turf";
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type { TimelineEvent, TimelineEventKind } from "@/api/timeline";
import {
  alertActionGlyph,
  alertChipImageId,
  flagImageId,
  markerSeverity,
  SIGNAL_IMAGE_ID,
} from "@/modules/labs/map/markerIcons";
import type { FadedEvent } from "./frames";

/**
 * Which kinds draw a mark at all.
 *
 * The other three — a phenology transition, a completed activity, a
 * recommendation — are properties of a BLOCK, not of a spot in it. Putting
 * them on a pin would invent a precision nobody recorded. They highlight
 * the block outline instead, and the rail carries the detail.
 */
export const MARK_KINDS: readonly TimelineEventKind[] = ["alert", "flag", "signal", "visit"];

/** Kinds that light up a block outline rather than dropping a pin. */
export const BLOCK_HIGHLIGHT_KINDS: readonly TimelineEventKind[] = [
  "stage",
  "activity",
  "recommendation",
];

export interface MarkProps {
  event_id: string;
  kind: TimelineEventKind;
  /** A registered marker image id. Resolved here, never in a style expression. */
  marker_icon: string;
  /** 0..1 from the fade curve. Drives `icon-opacity`. */
  opacity: number;
  /**
   * Placement priority. Lower sorts first and first placed wins, so the
   * freshest, most severe mark survives a crowded frame.
   */
  sort_key: number;
  block_id: string | null;
  block_name: string | null;
}

/** Block id -> a point guaranteed to sit inside the block. */
export type BlockAnchors = Map<string, [number, number]>;

/**
 * One anchor per block, for events that carry no coordinate of their own.
 *
 * `pointOnFeature` rather than a centroid: a centroid can land outside a
 * concave block — an L-shaped field, a pivot sector — which would float
 * the mark over a neighbour and point the reader at the wrong place.
 */
export function buildBlockAnchors(
  blocks: readonly { id: string; boundary: Polygon | null }[],
): BlockAnchors {
  const out: BlockAnchors = new Map();
  for (const b of blocks) {
    if (!b.boundary) continue;
    const feature: Feature<Polygon> = {
      type: "Feature",
      geometry: b.boundary,
      properties: {},
    };
    const coords = pointOnFeature(feature).geometry.coordinates;
    out.set(b.id, [coords[0], coords[1]]);
  }
  return out;
}

/** The registered image id for one event, or null when it draws no mark. */
export function markerIconFor(event: TimelineEvent): string | null {
  const severity = markerSeverity(event.severity);
  switch (event.kind) {
    case "alert":
      return alertChipImageId(alertActionGlyph(event.code), severity);
    case "flag":
      // A flag in the replay is always drawn as raised, whatever it became
      // later. The screen is a record of that day, and a flag that was
      // closed in August was not closed on the June frame the reader is
      // looking at.
      return flagImageId(severity, true);
    case "signal":
    case "visit":
      // A visit is a reading somebody took, the same category of thing a
      // signal observation is, so it takes the same quiet diamond rather
      // than a fifth shape nobody has learned yet.
      return SIGNAL_IMAGE_ID;
    default:
      return null;
  }
}

/** Severity to a placement rank. Lower wins. */
function severityRank(event: TimelineEvent): number {
  switch (markerSeverity(event.severity)) {
    case "critical":
      return 0;
    case "watch":
      return 1;
    default:
      return 2;
  }
}

/**
 * The mark layer's source for one frame.
 *
 * `faded` is what `visibleEvents` returned — the events within the fade
 * window, each with its opacity. Events with no coordinate borrow their
 * block's anchor; events with neither are dropped, because there is
 * nowhere honest to put them.
 */
export function buildMarks(
  faded: readonly FadedEvent[],
  anchors: BlockAnchors,
): FeatureCollection<Point, MarkProps> {
  const features: Feature<Point, MarkProps>[] = [];
  for (const { event, opacity } of faded) {
    const icon = markerIconFor(event);
    if (icon === null) continue;

    const coordinates =
      event.point?.coordinates ??
      (event.block_id ? anchors.get(event.block_id) : undefined) ??
      null;
    if (coordinates === null) continue;

    features.push({
      type: "Feature",
      id: undefined,
      geometry: { type: "Point", coordinates: [coordinates[0], coordinates[1]] },
      properties: {
        event_id: event.id,
        kind: event.kind,
        marker_icon: icon,
        opacity,
        // Fresh beats stale, and within one age the worse severity beats
        // the better one. Opacity is the age, so 1 - opacity puts today's
        // mark at 0 and a three-day-old one near 0.75.
        sort_key: (1 - opacity) * 10 + severityRank(event),
        block_id: event.block_id,
        block_name: event.block_name,
      },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * Blocks to outline on this frame, and how strongly.
 *
 * A block gets the highest opacity of any block-scoped event standing on
 * it, so a block with a stage change today and an activity from two days
 * ago reads as today's.
 */
export function buildBlockHighlights(faded: readonly FadedEvent[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const { event, opacity } of faded) {
    if (!BLOCK_HIGHLIGHT_KINDS.includes(event.kind)) continue;
    if (!event.block_id) continue;
    const existing = out.get(event.block_id) ?? 0;
    if (opacity > existing) out.set(event.block_id, opacity);
  }
  return out;
}
