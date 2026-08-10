import type { ActionItem, CellLocation } from "@/api/actionCenter";

/**
 * Cell coordinates as decimal degrees, 5 places (~1 m).
 *
 * Deliberately replaces the old `R2C3` zone label: a zone code is an index
 * into a grid config, which is meaningful to the engine and meaningless to
 * someone standing in a field. 5 dp is what Google/Apple Maps and handheld
 * GPS units accept by paste.
 */
export function formatCoords(cell: Pick<CellLocation, "lat" | "lon">): string | null {
  if (cell.lat === null || cell.lon === null) return null;
  return `${cell.lat.toFixed(5)}, ${cell.lon.toFixed(5)}`;
}

/** A geo: URI opens the device's own map app; the https fallback is for
 *  desktop browsers, which have no geo: handler. */
export function mapsUrl(cell: Pick<CellLocation, "lat" | "lon">): string | null {
  const coords = formatCoords(cell);
  if (coords === null) return null;
  return `https://www.google.com/maps/search/?api=1&query=${cell.lat},${cell.lon}`;
}

/** "cell 3 of 36" — an ordinal is cheaper to read than row/col arithmetic
 *  when two rows on the same block need telling apart. */
export function cellOrdinal(cell: CellLocation): string | null {
  if (cell.ordinal === null) return null;
  return cell.total === null ? `${cell.ordinal}` : `${cell.ordinal} / ${cell.total}`;
}

export function confidencePercent(confidence: string | null): number | null {
  if (confidence === null) return null;
  const n = Number(confidence);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

/** Localised title, falling back to English when no Arabic text was authored. */
export function itemTitle(item: ActionItem, isAr: boolean): string {
  return isAr ? (item.title_ar ?? item.title_en) : item.title_en;
}

export function itemDetail(item: ActionItem, isAr: boolean): string | null {
  return isAr ? (item.detail_ar ?? item.detail_en) : item.detail_en;
}
