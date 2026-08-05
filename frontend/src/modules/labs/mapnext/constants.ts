// Non-component constants for the Farm Console, kept out of the component
// files so react-refresh (fast refresh) stays happy.
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { Health, IndexCode } from "../map/types";

// Last farm the user looked at, so /labs/map with no :farmId can restore it.
// Shared by the console and the create-farm flow (which writes it on success).
export const LAST_FARM_KEY = "labs/map/lastFarm";

// Mirror the map's health palette so the rail dot, the inspector badge and
// the polygon fill all agree at a glance.
export const HEALTH_DOT: Record<Health, string> = {
  healthy: "#4f8e4a",
  watch: "#c98a18",
  critical: "#b24430",
  unknown: "#9c9c9c",
};

// The full index set the sub-block grid pipeline supports (what the map can
// colour by). The block-level time-series API only serves three of these —
// see BLOCK_LEVEL_INDICES — so only those can be charted for a whole block.
export const MAP_INDEX_ORDER: ApiIndexCode[] = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi", "ndmi"];
export const BLOCK_LEVEL_INDICES: IndexCode[] = ["ndvi", "ndre", "ndwi"];

export function isBlockLevel(c: ApiIndexCode): c is IndexCode {
  return c === "ndvi" || c === "ndre" || c === "ndwi";
}

// ---- agronomic families ---------------------------------------------------
//
// Indices grouped by the question they answer rather than by acronym: is the
// canopy growing, is it fed, is it thirsty. The Farm Console's first inspector
// filed them this way and printed the family as a heading above each index
// (#228); the grouping was dropped when the four grid-only indices arrived and
// broke the one-index-per-family symmetry (#234), leaving a flat grid and then
// a flat pill row. The dock restores it as one tab per family.
export type IndexFamilyKey = "vigour" | "nutrition" | "moisture";

export const INDEX_FAMILIES: { key: IndexFamilyKey; indices: ApiIndexCode[] }[] = [
  { key: "vigour", indices: ["ndvi", "evi", "savi"] },
  { key: "nutrition", indices: ["ndre", "gndvi"] },
  { key: "moisture", indices: ["ndwi", "ndmi"] },
];

// The one block-level index in each family — what that family's tab charts,
// since the grid-only members have no block-wide series to plot.
export const FAMILY_PRIMARY: Record<IndexFamilyKey, IndexCode> = {
  vigour: "ndvi",
  nutrition: "ndre",
  moisture: "ndwi",
};

// Family names, definitions, scales and band readings are i18n keys
// (`dock.family.*`, `dock.meaning.*`, `dock.def.*`, `dock.scale.*`,
// `dock.band.*`), not English literals in this table: they are read as tab
// labels and body copy now, and an English tab in the Arabic nav is a worse
// failure than the untranslated tooltip they used to be.
export const INDEX_META: Record<ApiIndexCode, { label: string; family: IndexFamilyKey }> = {
  ndvi: { label: "NDVI", family: "vigour" },
  evi: { label: "EVI", family: "vigour" },
  savi: { label: "SAVI", family: "vigour" },
  ndre: { label: "NDRE", family: "nutrition" },
  gndvi: { label: "GNDVI", family: "nutrition" },
  ndwi: { label: "NDWI", family: "moisture" },
  ndmi: { label: "NDMI", family: "moisture" },
};

// ---- value bands ----------------------------------------------------------
//
// What a reading MEANS, so the dock can say whether 0.31 is good news. Each
// entry is an inclusive upper bound plus the i18n key and severity tone for
// everything at or below it, ordered ascending and terminated by Infinity.
//
// The cut points are the published interpretation ranges for each formula AS
// THE BACKEND COMPUTES IT (backend/app/modules/indices/computation.py) — they
// are emphatically not interchangeable between indices, because the formulas
// are not. Two traps worth naming:
//
//   * `ndwi` here is McFeeters (GREEN - NIR)/(GREEN + NIR), a SURFACE-water
//     index. Its scale runs the opposite way to the canopy indices: strongly
//     negative is a healthy canopy, and anything above 0 is standing water.
//     Near zero is ambiguous between bare soil and wet ground.
//   * `ndmi` — not `ndwi` — is the leaf-moisture index, so it is the one whose
//     low end means water stress rather than "no water on the ground".
//
// Tone is the reading's own severity, not a verdict on the block: what counts
// as healthy also moves with growth stage, which `dock.readingCaveat` says on
// screen rather than pretending this table knows the crop calendar.
export interface IndexBand {
  /** Inclusive upper bound; the last band in each list is Infinity. */
  max: number;
  /** Key suffix under `dock.band.<code>.<key>`. */
  key: string;
  tone: Health;
}

export const INDEX_BANDS: Record<ApiIndexCode, IndexBand[]> = {
  ndvi: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "verySparse", tone: "critical" },
    { max: 0.4, key: "sparse", tone: "watch" },
    { max: 0.6, key: "developing", tone: "watch" },
    { max: 0.8, key: "dense", tone: "healthy" },
    { max: Infinity, key: "veryDense", tone: "healthy" },
  ],
  // EVI's blue-band and soil terms pull its mid-range below NDVI's for the
  // same canopy, so the cut points are not copied across.
  evi: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "verySparse", tone: "critical" },
    { max: 0.35, key: "sparse", tone: "watch" },
    { max: 0.55, key: "developing", tone: "watch" },
    { max: 0.75, key: "dense", tone: "healthy" },
    { max: Infinity, key: "veryDense", tone: "healthy" },
  ],
  savi: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "verySparse", tone: "critical" },
    { max: 0.35, key: "sparse", tone: "watch" },
    { max: 0.55, key: "developing", tone: "watch" },
    { max: 0.75, key: "dense", tone: "healthy" },
    { max: Infinity, key: "veryDense", tone: "healthy" },
  ],
  ndre: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "low", tone: "critical" },
    { max: 0.3, key: "moderate", tone: "watch" },
    { max: 0.45, key: "good", tone: "healthy" },
    { max: Infinity, key: "high", tone: "healthy" },
  ],
  gndvi: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "low", tone: "critical" },
    { max: 0.35, key: "moderate", tone: "watch" },
    { max: 0.55, key: "good", tone: "healthy" },
    { max: Infinity, key: "high", tone: "healthy" },
  ],
  ndwi: [
    { max: -0.4, key: "denseCanopy", tone: "healthy" },
    { max: -0.15, key: "vegetated", tone: "healthy" },
    { max: 0, key: "bareOrDamp", tone: "watch" },
    { max: 0.2, key: "standingWater", tone: "watch" },
    { max: Infinity, key: "openWater", tone: "critical" },
  ],
  ndmi: [
    { max: -0.2, key: "bare", tone: "unknown" },
    { max: 0, key: "severeStress", tone: "critical" },
    { max: 0.2, key: "stress", tone: "critical" },
    { max: 0.4, key: "moderate", tone: "watch" },
    { max: 0.6, key: "wellWatered", tone: "healthy" },
    { max: Infinity, key: "veryWet", tone: "healthy" },
  ],
};
