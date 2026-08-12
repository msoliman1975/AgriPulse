// Per-class area for the index legend.
//
// The one number a farm manager acts on is "how much of my farm is in
// trouble" — "24.1 ha very sparse", not a colour. Every grid cell already
// carries `area_m2`, clipped to the block boundary (so edge cells are
// smaller than cell_size²; summing the field is strictly more correct than
// counting cells and multiplying). Nothing here needs a new endpoint.
//
// Kept as pure functions in a .ts file, deliberately: MapLibre does not
// render under jsdom, so anything living inside the map component cannot be
// unit-tested. This can.
import type { GridCellWithValue } from "@/api/grid";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { gridRampColor } from "../map/gridRamp";
import { INDEX_BANDS, type IndexBand } from "../mapnext/constants";
import type { Health } from "../map/types";

/**
 * Which label vocabulary an index's bands read from.
 *
 * NDVI, EVI and SAVI share a band key set (and their meanings), as do NDRE
 * and GNDVI — only the cut points differ. Keying the copy on the vocabulary
 * rather than the index keeps one wording per concept instead of three
 * copies that drift.
 *
 * The dock's own `dock.band.<code>.<key>` strings stay per-index and stay
 * long: they are full explanations. These are chip labels for a legend row.
 */
export const BAND_VOCAB: Record<ApiIndexCode, string> = {
  ndvi: "canopy",
  evi: "canopy",
  savi: "canopy",
  ndre: "chlorophyll",
  gndvi: "chlorophyll",
  ndwi: "surfaceWater",
  ndmi: "leafMoisture",
};

/**
 * Where our own band copy already tells the reader to switch index, surface
 * it on that band's row. Only NDVI carries one today — `dock.band.ndvi
 * .veryDense` ends "use NDRE to tell a good canopy from an excellent one".
 * Do not invent entries here; add one only when the agronomy copy says so.
 */
export const LEGEND_HINT: Partial<Record<ApiIndexCode, { bandKey: string; suggest: string }>> = {
  ndvi: { bandKey: "veryDense", suggest: "NDRE" },
};

/** The shape `useFarmConsole`'s farm-grid query returns. */
export interface LegendGroup {
  blockId: string;
  cells: GridCellWithValue[];
}

export interface LegendRow {
  /** Key suffix under `legend.band.<code>.<key>`. */
  key: string;
  tone: Health;
  /** Inclusive upper bound; null when the band is unbounded above. */
  hi: number | null;
  /** Exclusive lower bound; null when the band is unbounded below. */
  lo: number | null;
  /** What the map paints for a value in this band. */
  color: string;
  areaM2: number;
  cellCount: number;
}

export interface LegendSummary {
  rows: LegendRow[];
  /** Area with a reading, i.e. the sum of every row. */
  coveredM2: number;
  /** Area whose cells exist but have no reading for this scene. */
  noDataM2: number;
  noDataCells: number;
  totalCells: number;
}

/**
 * A representative value for colouring the swatch. The open-ended bands have
 * no midpoint, so step just inside them — far enough to be visually distinct
 * from the neighbouring band, close enough to stay in the right ramp segment.
 */
function bandSampleValue(band: IndexBand, lo: number | null): number {
  if (!Number.isFinite(band.max)) return (lo ?? 0) + 0.1;
  if (lo === null) return band.max - 0.1;
  return (lo + band.max) / 2;
}

/**
 * Sum cell area per band for one index.
 *
 * `scopeBlockId` narrows to a single block; pass null for the whole farm.
 * Cells with no reading are NOT dropped into a band — they are reported
 * separately, so every hectare on screen is accounted for somewhere.
 */
export function computeLegend(
  groups: readonly LegendGroup[] | undefined,
  code: ApiIndexCode,
  scopeBlockId: string | null,
): LegendSummary {
  const bands = INDEX_BANDS[code] ?? [];
  const areaByKey = new Map<string, number>();
  const countByKey = new Map<string, number>();
  let noDataM2 = 0;
  let noDataCells = 0;
  let totalCells = 0;

  for (const group of groups ?? []) {
    if (scopeBlockId && group.blockId !== scopeBlockId) continue;
    for (const cell of group.cells) {
      const area = Number(cell.area_m2);
      // A non-finite or non-positive area is a broken row, not a zero-area
      // cell — the DB has a `area_m2 > 0` check constraint. Skip it entirely
      // rather than letting it distort a total.
      if (!Number.isFinite(area) || area <= 0) continue;
      totalCells += 1;

      const raw = cell.mean === null ? null : Number(cell.mean);
      const band =
        raw === null || !Number.isFinite(raw) ? null : (bands.find((b) => raw <= b.max) ?? null);
      if (!band) {
        noDataM2 += area;
        noDataCells += 1;
        continue;
      }
      areaByKey.set(band.key, (areaByKey.get(band.key) ?? 0) + area);
      countByKey.set(band.key, (countByKey.get(band.key) ?? 0) + 1);
    }
  }

  const rows: LegendRow[] = bands.map((band, i) => {
    const lo = i === 0 ? null : bands[i - 1].max;
    return {
      key: band.key,
      tone: band.tone,
      hi: Number.isFinite(band.max) ? band.max : null,
      lo,
      color: gridRampColor(bandSampleValue(band, lo)),
      areaM2: areaByKey.get(band.key) ?? 0,
      cellCount: countByKey.get(band.key) ?? 0,
    };
  });

  const coveredM2 = rows.reduce((sum, r) => sum + r.areaM2, 0);
  // Highest band first: the legend reads top-down like the scale it describes.
  rows.reverse();

  return { rows, coveredM2, noDataM2, noDataCells, totalCells };
}

/**
 * Range label for a row, derived from its own bounds rather than a hardcoded
 * 0..1 scale — NDWI's first band tops out at -0.4 and NDMI's at -0.2, so a
 * fabricated "0.00" floor would simply be wrong for them.
 */
export function formatRange(row: LegendRow, fmt: (n: number) => string): string {
  if (row.lo === null && row.hi !== null) return `≤ ${fmt(row.hi)}`;
  if (row.hi === null && row.lo !== null) return `> ${fmt(row.lo)}`;
  if (row.lo === null || row.hi === null) return "—";
  return `${fmt(row.lo)} – ${fmt(row.hi)}`;
}
