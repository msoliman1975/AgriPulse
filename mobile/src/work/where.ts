/**
 * Where a job is, and how to hand that to a maps app.
 *
 * A scout reads a title, a block name and an instruction, and then has to work
 * out which corner of which field that is. On a farm of forty blocks, in the
 * dark, that is the slowest part of the job — and it is the one part the app
 * already knows the answer to and was throwing away.
 *
 * Three sources of a position, and they are NOT equally good:
 *
 *   1. `pin_point`  — the exact spot a supervisor tapped. Ad-hoc dispatch only:
 *                     a CHECK on `scouting_visits` allows it for no other
 *                     origin, so it is null on everything the engine raises.
 *   2. `cell_point` — the centre of the one grid cell the visit names.
 *   3. the block centroid — the middle of the whole block.
 *
 * Only the first is a place. The other two are *averages of an area*, and a
 * scout walked to the middle of a 12-hectare block by a control that promised
 * "take me there" learns to distrust it. So the precision travels with the
 * point and the screen says which one it got. A job with none of the three
 * disables the control rather than guessing.
 */

import type { Block, GeoJsonPoint, WorkItem } from "@/api/client";

/** How exactly we know where this is. Ordered best to worst. */
export type Precision = "exact" | "cell" | "block";

export interface Destination {
  lat: number;
  lon: number;
  precision: Precision;
}

/**
 * A GeoJSON point as latitude/longitude.
 *
 * GeoJSON is `[longitude, latitude]` — the opposite order to how the pair is
 * spoken, written on a sign, and typed into every maps app. This function is
 * the only place in the app that unpacks it, so the swap can be got wrong once
 * rather than at each call site. A swap does not throw: it silently sends a
 * scout in Egypt to a point in the Indian Ocean.
 *
 * Anything that is not a finite pair returns null. `0, 0` is refused too: it is
 * the shape a half-populated geometry takes, it is 600 km off the coast of
 * Ghana, and no farm this app serves is there.
 */
export function pointOf(point: GeoJsonPoint | null | undefined): { lat: number; lon: number } | null {
  if (!point || point.type !== "Point" || !Array.isArray(point.coordinates)) return null;
  const [lon, lat] = point.coordinates;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  if (lat === 0 && lon === 0) return null;
  return { lat, lon };
}

/**
 * The best position known for one job.
 *
 * `visitPoints` is null for board work and for a visit whose detail has not
 * come back yet — in both cases the block centroid still answers, which is why
 * the button is usable on first paint rather than after a round trip.
 */
export function destinationOf(
  item: WorkItem,
  visitPoints: { pin_point: GeoJsonPoint | null; cell_point: GeoJsonPoint | null } | null,
  block: Block | null,
): Destination | null {
  const exact = pointOf(visitPoints?.pin_point);
  if (exact) return { ...exact, precision: "exact" };

  const cell = pointOf(visitPoints?.cell_point);
  if (cell) return { ...cell, precision: "cell" };

  // Guarded on the id as well as the object: a caller handing over the wrong
  // farm's block list would otherwise route the scout to a different farm,
  // confidently and with a plausible-looking pin.
  if (block && block.id === item.block_id) {
    const centre = pointOf(block.centroid);
    if (centre) return { ...centre, precision: "block" };
  }
  return null;
}

/**
 * A link that opens driving directions in whatever maps app is installed.
 *
 * The universal Google Maps URL rather than a `geo:` URI or
 * `google.navigation:`. All three work on Android, and this one is the only
 * one that also works in a browser, which is where the app is developed and
 * tested — a control that can only be exercised on a handset is a control that
 * gets shipped broken. Google Maps registers an intent filter for this path,
 * so on a phone it opens the app on the directions screen, and on a handset
 * without it the browser answers.
 *
 * No origin is given. Supplying one would pin the route to wherever the scout
 * was when the screen rendered; leaving it out lets the maps app use the live
 * fix, which is the thing that is actually moving.
 */
export function directionsUrl(dest: Destination): string {
  const q = `${dest.lat.toFixed(6)},${dest.lon.toFixed(6)}`;
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(q)}&travelmode=driving`;
}
