// How much detail a thermal reading can honestly carry.
//
// LST / CWSI / SMI come from Landsat's thermal sensor at **100 m native**,
// resampled by USGS onto the 30 m grid the other bands use. The 30 m is a
// delivery grid, not a measurement — treating it as one is the single
// easiest way to overstate what this data says.
//
// Against real block geometry on the reference farm:
//
//   smallest block  0.53 ha  -> a fraction of ONE thermal pixel
//   average block   3.10 ha  -> ~158 m a side, roughly 3 pixels
//   largest block  25.07 ha  -> about 5x5 pixels, a real surface
//
// So a farm-wide reading is honest, a large block is a real signal, and a
// small block is inheriting its farm's value dressed up as its own. The
// UI has to say which of those a reader is looking at.

import { THERMAL_INDEX_CODES, type ThermalIndexCode } from "@/api/indices";

/** Native ground sample distance of the thermal band, in metres. */
export const THERMAL_NATIVE_RESOLUTION_M = 100;

/** Ground area of one thermal pixel, in hectares (100 m x 100 m). */
export const THERMAL_PIXEL_AREA_HA = 1;

/** An area covering fewer than this many thermal pixels cannot resolve detail. */
const MARGINAL_PIXEL_COUNT = 9; // a 3x3 neighbourhood

export function isThermalIndex(code: string): code is ThermalIndexCode {
  return (THERMAL_INDEX_CODES as readonly string[]).includes(code);
}

/**
 * How much a thermal value for an area of `areaHa` can be trusted.
 *
 * - `subPixel`   — smaller than one thermal pixel. The value is the pixel
 *   the area sits inside, shared with whatever else is in that pixel.
 * - `marginal`   — a handful of pixels. A trend is readable; within-area
 *   variation is not.
 * - `resolved`   — enough pixels to show a pattern across the area.
 */
export type ThermalConfidence = "subPixel" | "marginal" | "resolved";

export function thermalConfidence(
  areaHa: number | null | undefined,
): ThermalConfidence | null {
  if (areaHa === null || areaHa === undefined || !Number.isFinite(areaHa) || areaHa <= 0) {
    return null;
  }
  const pixels = areaHa / THERMAL_PIXEL_AREA_HA;
  if (pixels < 1) return "subPixel";
  if (pixels < MARGINAL_PIXEL_COUNT) return "marginal";
  return "resolved";
}

/** Roughly how many thermal pixels cover an area, for the caller's label. */
export function thermalPixelCount(areaHa: number | null | undefined): number | null {
  if (areaHa === null || areaHa === undefined || !Number.isFinite(areaHa) || areaHa <= 0) {
    return null;
  }
  return Math.round(areaHa / THERMAL_PIXEL_AREA_HA);
}
