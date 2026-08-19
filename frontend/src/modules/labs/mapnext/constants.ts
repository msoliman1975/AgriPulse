// Non-component constants for the Farm Console, kept out of the component
// files so react-refresh (fast refresh) stays happy.
import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { THERMAL_INDEX_CODES } from "@/api/indices";
import type { Health } from "../map/types";

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

// What the map can colour by, in two lists because the two consoles can draw
// different things.
//
// `MAP_INDEX_ORDER` is everything, and it is what the tables below are keyed
// on — INDEX_META, INDEX_BANDS and console/indexClasses.ts all cover all
// thirteen, enforced by indexFamilies.test.ts.
//
// But the PICKER's options are a per-console decision, passed in rather than
// read from here, because the two consoles render an index by different
// means. The pixel console (/labs/map-v2) draws the index COG itself, which
// exists for thermal exactly as it does for optical. The live console
// (/labs/map) draws only the sub-block grid mesh, and thermal has no cells in
// it: `grid_configs` are per-product and only the optical product has one, so
// `list_cells_for_scene` returns nothing for a Landsat scene and no thermal
// cell row is ever written. Offering LST there would be a chip that paints an
// empty farm — which is why `OPTICAL_INDEX_ORDER` exists as its own export
// rather than the callers slicing this one by a magic number.
//
// The thermal three come from `landsat_c2_l2_st` rather than `s2_l2a`: a
// different satellite on a different cadence at a tenth the resolution. The
// console reads them through the same routes by naming the index it is about
// to draw (`?index=`), so each product's stream answers for itself.
// `isThermalIndex` is what everything downstream branches on.
export const OPTICAL_INDEX_ORDER: ApiIndexCode[] = [
  "ndvi",
  "ndre",
  "ndwi",
  "evi",
  "savi",
  "gndvi",
  "ndmi",
  "bsi",
  "msi",
  "msavi",
];

export const THERMAL_INDEX_ORDER: ApiIndexCode[] = ["lst", "cwsi", "smi"];

export const MAP_INDEX_ORDER: ApiIndexCode[] = [...OPTICAL_INDEX_ORDER, ...THERMAL_INDEX_ORDER];

const THERMAL_SET: ReadonlySet<string> = new Set<string>(THERMAL_INDEX_CODES);

/**
 * Whether an index comes from the thermal product.
 *
 * Derived from the API module's own list rather than restated, so adding a
 * thermal index there cannot leave this predicate behind — the failure that
 * would produce is silent and total: the index would be drawn as though it
 * were 10 m Sentinel-2, against the wrong scene stream.
 */
export function isThermalIndex(code: ApiIndexCode): boolean {
  return THERMAL_SET.has(code);
}

/**
 * Indices whose reading gets WORSE as the number climbs.
 *
 * Ten of the thirteen are "higher is a better canopy", and the dock's delta
 * colouring assumed that for all of them — so a block whose surface
 * temperature rose 6 °C in a week was painted green, and rising MSI (water
 * stress) and rising NDWI (standing water on the block) with it.
 *
 * The tone in INDEX_BANDS already encodes this per band; this set is the same
 * fact stated for a CHANGE, which has no band. Keep the two in step: an index
 * whose band tones descend belongs here.
 */
export const HIGHER_IS_WORSE: ReadonlySet<ApiIndexCode> = new Set<ApiIndexCode>([
  "ndwi", // McFeeters surface water: above zero is water standing on the block
  "msi", // SWIR/NIR ratio, inverted — high is stressed
  "bsi", // bare soil: high is exposed ground
  "lst", // canopy heating up
  "cwsi", // stomata closing
]);

// ---- agronomic families ---------------------------------------------------
//
// Indices grouped by the question they answer rather than by acronym: is the
// canopy growing, is it fed, is it thirsty. The Farm Console's first inspector
// filed them this way and printed the family as a heading above each index
// (#228); the grouping was dropped when the four grid-only indices arrived and
// broke the one-index-per-family symmetry (#234), leaving a flat grid and then
// a flat pill row. The dock restores it as one tab per family.
export type IndexFamilyKey = "vigour" | "nutrition" | "moisture" | "thermal";

// `bsi` files under vigour and `msi` under moisture rather than earning a
// fourth "soil" tab. The family question vigour answers is "is the canopy
// covering the ground", and bare soil is that question inverted. (The other
// half of that argument used to be that a soil family would have had no
// series to chart. That was never true — see FAMILY_PRIMARY.)
//
// The thermal three get their OWN family rather than being filed under
// moisture, where two of them arguably belong by subject. Two reasons, and
// the second is the deciding one:
//
//   * they answer a different question — not "how much water is in the leaf"
//     but "is the canopy cooling itself", which is transpiration rather than
//     content;
//   * they come from a different SENSOR at a tenth the resolution and on a
//     different cadence. Mixing a 100 m reading into a tab of 10 m ones
//     presents them as interchangeable evidence about the same patch of
//     ground, and they are not. The tab boundary is where the resolution
//     caveat can be stated once instead of per index.
export const INDEX_FAMILIES: { key: IndexFamilyKey; indices: ApiIndexCode[] }[] = [
  { key: "vigour", indices: ["ndvi", "evi", "savi", "msavi", "bsi"] },
  { key: "nutrition", indices: ["ndre", "gndvi"] },
  { key: "moisture", indices: ["ndwi", "ndmi", "msi"] },
  { key: "thermal", indices: ["lst", "cwsi", "smi"] },
];

// The index a family tab charts when it opens. Every member is chartable —
// `/blocks/{id}/indices/{code}/timeseries` reads the daily continuous
// aggregate by `index_code` and the ingest task writes a row per computed
// index — so this is a starting point, not a restriction: clicking any card
// in the tab charts that index instead.
//
// It used to be "the one block-level index in the family", nullable because
// thermal had none. That reading of the API was wrong. The route was never
// limited to the three columns `blocks_summary_router` publishes; only the
// FARM-WIDE summary is, and the dock does not read the summary.
export const FAMILY_PRIMARY: Record<IndexFamilyKey, ApiIndexCode> = {
  vigour: "ndvi",
  nutrition: "ndre",
  moisture: "ndwi",
  thermal: "lst",
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
  msavi: { label: "MSAVI", family: "vigour" },
  ndre: { label: "NDRE", family: "nutrition" },
  gndvi: { label: "GNDVI", family: "nutrition" },
  ndwi: { label: "NDWI", family: "moisture" },
  ndmi: { label: "NDMI", family: "moisture" },
  bsi: { label: "BSI", family: "vigour" },
  msi: { label: "MSI", family: "moisture" },
  lst: { label: "LST", family: "thermal" },
  cwsi: { label: "CWSI", family: "thermal" },
  smi: { label: "SMI", family: "thermal" },
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
  // MSAVI2 — savi with the soil factor solved per pixel instead of pinned at
  // L = 0.5. It tracks SAVI within a few hundredths over real reflectance, so
  // it reads on the soil-adjusted scale and NOT on NDVI's.
  //
  // Cut points are deliberately identical to `console/indexClasses.ts`
  // INDEX_CLASSES for msavi, so the dock's reading and the map's legend never
  // name the same value differently — the discipline `bsi` set. They are
  // therefore SAVI's *map* boundaries, which is why they do not match the
  // `savi` row a few lines up: that row and its own map entry have disagreed
  // since before the discipline existed, and reproducing that drift in a new
  // index would be copying the wrong half.
  msavi: [
    { max: 0.1, key: "bare", tone: "unknown" },
    { max: 0.2, key: "verySparse", tone: "critical" },
    { max: 0.4, key: "sparse", tone: "watch" },
    { max: 0.6, key: "developing", tone: "watch" },
    { max: 0.8, key: "dense", tone: "healthy" },
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
  // Bare soil. Reads the ground rather than the canopy, so the tones run the
  // opposite way to the vigour indices it sits beside: negative is closed
  // canopy (good), positive is exposed ground (bad). Mid-season that means
  // plant loss or canopy gaps; right after planting the same reading is
  // simply "not established yet", which is what `dock.readingCaveat` is for.
  // Boundaries deliberately identical to `console/indexClasses.ts` INDEX_CLASSES
  // for bsi, so the dock's reading and the map's legend never name the same
  // value differently. (The older indices predate that discipline — ndmi's two
  // tables disagree by design-drift, not intent.)
  bsi: [
    { max: -0.3, key: "closedCanopy", tone: "healthy" },
    { max: -0.1, key: "mostlyCovered", tone: "healthy" },
    { max: 0, key: "thinning", tone: "watch" },
    { max: 0.15, key: "patchy", tone: "watch" },
    { max: 0.3, key: "mostlyBare", tone: "critical" },
    { max: Infinity, key: "bare", tone: "critical" },
  ],
  // ⚠️ MSI is a RATIO (~0.2–2.0+), not a normalized difference, and it is
  // INVERTED: low = well watered, high = stressed. So unlike every other
  // entry in this table the tones descend rather than ascend. Cut points are
  // Rock et al. (1986): <0.4 low stress, 0.4–1.0 moderate, >1.0 high.
  msi: [
    { max: 0.4, key: "wellWatered", tone: "healthy" },
    { max: 0.6, key: "adequate", tone: "healthy" },
    { max: 0.8, key: "mildStress", tone: "watch" },
    { max: 1.0, key: "moderateStress", tone: "watch" },
    { max: 1.6, key: "highStress", tone: "critical" },
    { max: Infinity, key: "severeStress", tone: "critical" },
  ],

  // ---- thermal ------------------------------------------------------------
  //
  // Cut points and tones are IDENTICAL to `console/indexClasses.ts`
  // INDEX_CLASSES for the same three codes — the discipline `bsi` and `msavi`
  // set, and a strict requirement here rather than a nicety: on the pixel
  // console the dock's reading and the map legend describe the very same
  // number taken from the very same raster, so naming it `hot` in one place
  // and `warm` in the other is a visible contradiction on one screen.
  //
  // ⚠️ `lst` is in DEGREES CELSIUS. Every other row in this table is a ratio
  // bounded near [-1, 1]; anything that formats or scales a band value has to
  // read the unit rather than assume one. See `dockFormat`.
  lst: [
    { max: 20, key: "cool", tone: "healthy" },
    { max: 30, key: "mild", tone: "healthy" },
    { max: 38, key: "warm", tone: "watch" },
    { max: 45, key: "hot", tone: "watch" },
    { max: 52, key: "veryHot", tone: "critical" },
    { max: Infinity, key: "extreme", tone: "critical" },
  ],
  cwsi: [
    { max: 0.2, key: "unstressed", tone: "healthy" },
    { max: 0.4, key: "mild", tone: "healthy" },
    { max: 0.6, key: "moderate", tone: "watch" },
    { max: 0.8, key: "high", tone: "critical" },
    { max: Infinity, key: "severe", tone: "critical" },
  ],
  smi: [
    { max: 0.2, key: "veryDry", tone: "critical" },
    { max: 0.4, key: "dry", tone: "critical" },
    { max: 0.6, key: "moderate", tone: "watch" },
    { max: 0.8, key: "moist", tone: "healthy" },
    { max: Infinity, key: "wet", tone: "watch" },
  ],
};
