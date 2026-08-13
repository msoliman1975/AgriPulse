// What an index value MEANS, as a set of discrete classes — and the single
// source for every colour on the map.
//
// One table feeds three consumers that used to disagree:
//
//   * the pixel layer, as a TiTiler interval colormap (`titilerColormap`);
//   * the legend rows the user reads (`classesFor`, high → low);
//   * the block fill, which paints the class of the block's mean.
//
// That is the whole point. The previous design sampled a CONTINUOUS ramp at
// each band's midpoint to make a legend swatch, so a swatch matched the pixels
// at exactly one value per band and nowhere else — and because the ramp's own
// stops (0, 0.3, 0.6, 0.85) had nothing to do with the band edges, no class
// boundary was visible on the map at all. Discrete classes make agreement
// structural instead of something to keep an eye on.
//
// COLOUR IS A VERDICT, NOT A QUANTITY. Red always means bad for the crop,
// whatever the index — so NDWI, whose scale runs the other way (McFeeters
// surface water: high = standing water = bad), is ordered the other way here
// too. Two classes deliberately sit OUTSIDE the verdict ramp because they
// describe a different condition rather than a worse one: water/cloud under a
// vegetation index, and saturation at the top of NDMI.
//
// The boundaries are the published interpretation ranges for each formula AS
// THE BACKEND COMPUTES IT (backend/app/modules/indices/computation.py), signed
// off 2026-08-12. Sources per index are named on each table below. They are
// emphatically not interchangeable between indices, because the formulas are
// not.
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { Health } from "../map/types";

// ---- the verdict scale ----------------------------------------------------
//
// ColorBrewer RdYlGn, 6-class: the conventional vegetation ramp, and one that
// steps monotonically in LIGHTNESS as well as hue, so the ordering survives
// greyscale and red–green colour deficiency even though the scheme is not
// formally colourblind-safe. Named by verdict rather than by hue so a reader
// of this table cannot accidentally reorder it into a prettier gradient.
const CRITICAL = "#d73027";
const CRITICAL_LOW = "#fc8d59";
const WATCH = "#fee08b";
const WATCH_HIGH = "#d9ef8b";
const HEALTHY = "#91cf60";
const HEALTHY_HIGH = "#1a9850";

/** Outside the verdict ramp: this pixel is not vegetation at all. */
const WATER = "#3f7fb5";
/** Outside the verdict ramp: wet enough to be its own problem. */
const SATURATED = "#2c8c9e";

/** Cells and pixels with no usable reading. Also the legend's "no reading". */
export const NO_DATA_COLOR = "#9ca3af";

export interface IndexClass {
  /**
   * Inclusive upper bound; the last class in each list is Infinity. Same
   * convention as the dock's band table — `classes.find((c) => v <= c.max)`.
   */
  max: number;
  /** Key suffix under `legend.class.<vocab>.<key>`. */
  key: string;
  /**
   * Severity for the rail dot and the dock badge. The two non-verdict classes
   * report `watch`: "there is water here" and "this is saturated" both mean
   * go and look, and `unknown` would read as missing data rather than as a
   * finding.
   */
  tone: Health;
  /** The exact colour painted for this class — on the pixels AND in the legend. */
  color: string;
}

/**
 * Which label vocabulary an index's classes read from.
 *
 * NDVI, EVI and SAVI share a class key set (and their meanings), as do NDRE
 * and GNDVI — only the cut points differ. Keying the copy on the vocabulary
 * rather than the index keeps one wording per concept instead of three copies
 * that drift.
 */
export const CLASS_VOCAB: Record<ApiIndexCode, string> = {
  ndvi: "canopy",
  evi: "canopy",
  savi: "canopy",
  ndre: "chlorophyll",
  gndvi: "chlorophyll",
  ndwi: "surfaceWater",
  ndmi: "leafMoisture",
  bsi: "bareSoil",
  msi: "moistureStress",
};

// Canopy-cover indices. Boundaries per the USGS remote-sensing-phenology and
// NASA Earthdata readings: ≤0.1 barren rock/sand/snow, ~0.2–0.5 sparse or
// senescing crops, 0.6–0.9 dense canopy at peak growth.
//
// The `water` class at the bottom is new. Negative NDVI is water, snow or
// cloud — not dry ground — and folding it into "bare soil" made a flooded
// corner or a cloud shadow read as a bare patch.
const CANOPY = (bare: number, sparse: number, developing: number, dense: number, veryDense: number): IndexClass[] => [
  { max: 0, key: "water", tone: "watch", color: WATER },
  { max: bare, key: "bare", tone: "critical", color: CRITICAL },
  { max: sparse, key: "verySparse", tone: "critical", color: CRITICAL_LOW },
  { max: developing, key: "sparse", tone: "watch", color: WATCH },
  { max: dense, key: "developing", tone: "watch", color: WATCH_HIGH },
  { max: veryDense, key: "dense", tone: "healthy", color: HEALTHY },
  { max: Infinity, key: "veryDense", tone: "healthy", color: HEALTHY_HIGH },
];

const CHLOROPHYLL = (bare: number, low: number, moderate: number, good: number): IndexClass[] => [
  { max: bare, key: "bare", tone: "critical", color: CRITICAL },
  { max: low, key: "low", tone: "critical", color: CRITICAL_LOW },
  { max: moderate, key: "moderate", tone: "watch", color: WATCH },
  { max: good, key: "good", tone: "healthy", color: HEALTHY },
  { max: Infinity, key: "high", tone: "healthy", color: HEALTHY_HIGH },
];

export const INDEX_CLASSES: Record<ApiIndexCode, IndexClass[]> = {
  // (NIR − RED) / (NIR + RED).
  ndvi: CANOPY(0.1, 0.2, 0.4, 0.6, 0.8),

  // 2.5(NIR − RED) / (NIR + 6·RED − 7.5·BLUE + 1). EVI's blue-band and soil
  // terms genuinely pull its mid-range below NDVI's for the same canopy, so
  // its cut points are lower and are NOT copied from NDVI.
  evi: CANOPY(0.1, 0.2, 0.35, 0.55, 0.75),

  // 1.5(NIR − RED) / (NIR + RED + 0.5). SAVI used to borrow EVI's cut points;
  // that was wrong. The 1.5 gain in the numerator largely cancels the soil
  // term in the denominator, so SAVI lands close to NDVI in magnitude for the
  // same canopy — reading it on EVI's scale flattered every block by about one
  // class through the middle of the range.
  savi: CANOPY(0.1, 0.2, 0.4, 0.6, 0.8),

  // (NIR − RedEdge₁) / (NIR + RedEdge₁), red_edge_1 = B5 at 705 nm.
  //
  // Published NDRE tables disagree violently — one widely cited agronomy
  // source puts healthy crops at 0.6–1.0 — because they assume a different
  // red-edge band. B5 sits close to red and therefore returns materially
  // lower values than a B6/B7 formulation, so those numbers do not transfer.
  // These are a B5 reading, and `legend.relativeCaveat` says on screen that
  // NDRE is best read as the spread across one field on one date rather than
  // against absolute thresholds.
  ndre: CHLOROPHYLL(0.1, 0.2, 0.3, 0.45),

  // (NIR − GREEN) / (NIR + GREEN). Saturates later than NDVI over dense
  // canopy, which is why its upper boundaries sit higher.
  gndvi: CHLOROPHYLL(0.1, 0.2, 0.35, 0.55),

  // (GREEN − NIR) / (GREEN + NIR) — McFeeters 1996, SURFACE water.
  //
  // Ordered opposite to every other table here, and that is the point: this
  // index's healthy end is its NEGATIVE end. > 0 is McFeeters' own threshold
  // for open water (0–0.1 in common practice); a dense canopy reads well
  // below −0.15. The numbers were always right — the old ramp painted them
  // backwards, rendering the healthiest class as a blend of the no-data grey
  // and red while standing water came out the most inviting colour on screen.
  ndwi: [
    { max: -0.4, key: "denseCanopy", tone: "healthy", color: HEALTHY_HIGH },
    { max: -0.15, key: "vegetated", tone: "healthy", color: HEALTHY },
    { max: 0, key: "bareOrDamp", tone: "watch", color: WATCH },
    { max: 0.2, key: "standingWater", tone: "critical", color: CRITICAL_LOW },
    { max: Infinity, key: "openWater", tone: "critical", color: CRITICAL },
  ],

  // (NIR − SWIR₁) / (NIR + SWIR₁) — leaf moisture, per the EOS / Sentinel Hub
  // interpretation table for B8/B11.
  //
  // Rebuilt. The shipped table called everything below −0.20 "bare soil"; the
  // published one puts bare soil at −0.80 and below, with −0.80 → −0.20 being
  // progressively sparse canopy. The whole scale was about 0.6 low, so a
  // thinly covered but perfectly healthy block read as bare ground.
  //
  // Two further corrections. NDMI confounds canopy COVER with water CONTENT —
  // the same value can be a thin canopy with plenty of water or a full canopy
  // under stress — so the class copy names both rather than asserting stress
  // alone. And the top of the scale is not simply "best": above 0.80 the
  // published reading is full cover OR WATERLOGGING, which is a problem, so it
  // leaves the verdict ramp for the saturated colour.
  ndmi: [
    { max: -0.8, key: "bare", tone: "critical", color: CRITICAL },
    { max: -0.2, key: "verySparse", tone: "critical", color: CRITICAL_LOW },
    { max: 0.2, key: "stressed", tone: "watch", color: WATCH },
    { max: 0.4, key: "mildStress", tone: "watch", color: WATCH_HIGH },
    { max: 0.6, key: "dense", tone: "healthy", color: HEALTHY },
    { max: 0.8, key: "veryDense", tone: "healthy", color: HEALTHY_HIGH },
    { max: Infinity, key: "saturated", tone: "watch", color: SATURATED },
  ],

  // ((SWIR₁ + RED) − (NIR + BLUE)) / ((SWIR₁ + RED) + (NIR + BLUE)) —
  // Rikimaru et al. 2002, further validated in Nguyen et al. 2021 (Land 10:231)
  // for separating fallow from cropped land.
  //
  // Ordered the same way as NDWI and for the same reason: this index's healthy
  // end is its NEGATIVE end. Negative means canopy reflectance dominates the
  // pixel, positive means bare ground does. So the verdict ramp runs downhill
  // as the number goes up.
  //
  // The reading is stage-dependent in a way the colour cannot express: bare
  // ground three weeks after planting is expected, and the same value at peak
  // canopy is plant loss. `dock.readingCaveat` carries that on screen rather
  // than this table pretending to know the crop calendar.
  bsi: [
    { max: -0.3, key: "closedCanopy", tone: "healthy", color: HEALTHY_HIGH },
    { max: -0.1, key: "mostlyCovered", tone: "healthy", color: HEALTHY },
    { max: 0, key: "thinning", tone: "watch", color: WATCH_HIGH },
    { max: 0.15, key: "patchy", tone: "watch", color: WATCH },
    { max: 0.3, key: "mostlyBare", tone: "critical", color: CRITICAL_LOW },
    { max: Infinity, key: "bare", tone: "critical", color: CRITICAL },
  ],

  // SWIR₁ / NIR — Rock et al. 1986. Cut points from the common reading:
  // <0.4 high moisture content, 0.4–1.0 moderate stress, >1.0 high stress.
  //
  // The only RATIO in this table, and the only index whose value is not
  // bounded to [-1, 1] — real pixels run roughly 0.2 to 2.0+, so nothing here
  // may assume a normalized-difference range.
  //
  // It also runs backwards: HIGH means stressed. Because colour is a verdict
  // rather than a quantity, the ramp is ordered exactly as it is for every
  // other index — good at the top of the list, bad at the bottom — and it is
  // the NUMBERS that ascend against it.
  //
  // Confounder named in the class copy rather than hidden: open water drives
  // NIR toward zero, which sends the ratio very high, so standing water lands
  // in the same top class as a parched canopy. NDMI separates the two at its
  // low end; MSI cannot, which is a reason to read them together.
  msi: [
    { max: 0.4, key: "wellWatered", tone: "healthy", color: HEALTHY_HIGH },
    { max: 0.6, key: "adequate", tone: "healthy", color: HEALTHY },
    { max: 0.8, key: "mildStress", tone: "watch", color: WATCH_HIGH },
    { max: 1.0, key: "moderateStress", tone: "watch", color: WATCH },
    { max: 1.6, key: "highStress", tone: "critical", color: CRITICAL_LOW },
    { max: Infinity, key: "severeStress", tone: "critical", color: CRITICAL },
  ],
};

/** Indices whose classes should be read relatively, not as absolutes. */
export const READ_RELATIVELY: ReadonlySet<ApiIndexCode> = new Set<ApiIndexCode>(["ndre"]);

/**
 * Where our own class copy tells the reader to switch index, surface it on
 * that class's row. Only NDVI carries one today: above 0.80 NDVI saturates and
 * NDRE separates a good canopy from an excellent one. Do not invent entries —
 * add one only when the agronomy copy says so.
 */
export const CLASS_HINT: Partial<Record<ApiIndexCode, { classKey: string; suggest: string }>> = {
  ndvi: { classKey: "veryDense", suggest: "NDRE" },
};

/** Classes for an index, lowest first — the order the boundaries are defined in. */
export function classesFor(code: ApiIndexCode): IndexClass[] {
  return INDEX_CLASSES[code] ?? [];
}

/**
 * The class a reading falls in, or null when there is no reading. Mirrors the
 * inclusive-upper-bound convention above, so a value exactly on a boundary
 * belongs to the LOWER class — the same rule the tile colormap applies.
 */
export function classify(code: ApiIndexCode, value: number | null): IndexClass | null {
  if (value === null || !Number.isFinite(value)) return null;
  return classesFor(code).find((c) => value <= c.max) ?? null;
}

/**
 * Lower bound of a class — the previous class's `max`, or null for the first.
 * Kept as a function rather than a second field so the boundaries live in
 * exactly one place and cannot be edited into disagreement.
 */
export function lowerBound(code: ApiIndexCode, index: number): number | null {
  if (index <= 0) return null;
  return classesFor(code)[index - 1].max;
}

/**
 * Bin edges for a pixel histogram, ascending, as TiTiler's `histogram_bins`
 * wants them: N+1 edges for N classes.
 *
 * The open ends are clamped to values no real index reaches. Every index here
 * is a normalised difference bounded by [-1, 1] EXCEPT EVI and SAVI, whose
 * gain terms can push slightly outside it over bright soil, so the clamp is
 * wide enough to keep those pixels inside the first and last bins instead of
 * silently dropping them from the totals.
 */
export const HISTOGRAM_FLOOR = -3;
export const HISTOGRAM_CEILING = 3;

export function histogramBins(code: ApiIndexCode): number[] {
  const classes = classesFor(code);
  const edges = [HISTOGRAM_FLOOR];
  for (const c of classes) edges.push(Number.isFinite(c.max) ? c.max : HISTOGRAM_CEILING);
  return edges;
}

/**
 * The class table as a TiTiler "intervals" colormap: a JSON array of
 * `[[min, max], [r, g, b, a]]`.
 *
 * Intervals are half-open `[min, max)` on TiTiler's side while this table is
 * inclusive-upper. The difference is one float ulp at each boundary and it
 * only ever moves a pixel sitting EXACTLY on a cut point by one class, which
 * is why `classify` documents the same rule rather than pretending the two
 * agree perfectly.
 *
 * Deliberately NOT paired with `rescale`: rescale stretches values into 0–255
 * before the colormap is applied, which would make every interval here point
 * at the wrong data. Pixels outside every interval (no-data) render
 * transparent, so the satellite base shows through where there is no reading.
 */
export function titilerColormap(code: ApiIndexCode): string {
  const classes = classesFor(code);
  const intervals = classes.map((c, i) => {
    const min = i === 0 ? HISTOGRAM_FLOOR : classes[i - 1].max;
    const max = Number.isFinite(c.max) ? c.max : HISTOGRAM_CEILING;
    return [[min, max], rgba(c.color)];
  });
  return JSON.stringify(intervals);
}

function rgba(hex: string): [number, number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 255];
}

/**
 * Range label for a class, derived from its own bounds rather than a
 * hardcoded 0..1 scale — NDWI's first class tops out at -0.40 and NDMI's at
 * -0.80, so a fabricated "0.00" floor would simply be wrong for them.
 */
export function formatRange(lo: number | null, hi: number, fmt: (n: number) => string): string {
  const hasHi = Number.isFinite(hi);
  if (lo === null && hasHi) return `≤ ${fmt(hi)}`;
  if (!hasHi && lo !== null) return `> ${fmt(lo)}`;
  if (lo === null || !hasHi) return "—";
  return `${fmt(lo)} – ${fmt(hi)}`;
}
