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
import type { AnyIndexCode } from "@/api/indices";
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
export const CLASS_VOCAB: Record<AnyIndexCode, string> = {
  ndvi: "canopy",
  evi: "canopy",
  savi: "canopy",
  msavi: "canopy",
  ndre: "chlorophyll",
  gndvi: "chlorophyll",
  ndwi: "surfaceWater",
  ndmi: "leafMoisture",
  bsi: "bareSoil",
  msi: "moistureStress",
  lst: "surfaceTemp",
  cwsi: "waterStress",
  smi: "soilMoisture",
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

export const INDEX_CLASSES: Record<AnyIndexCode, IndexClass[]> = {
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

  // (2·NIR + 1 − √((2·NIR + 1)² − 8·(NIR − RED))) / 2 — MSAVI2, Qi et al. 1994.
  //
  // Same boundaries as SAVI, on purpose. MSAVI2 is SAVI with L solved per
  // pixel rather than fixed at 0.5, so the two land within a few hundredths
  // of each other over real reflectance — they are the same reading of the
  // same question, one with the soil correction tuned. Giving them different
  // legends would make the pair incomparable, which is the only reason to
  // carry both.
  //
  // (Whether the soil-adjusted pair should sit on NDVI's boundaries at all is
  // a live question — measured against orchard-over-sand reflectance both read
  // ~0.15 below NDVI at partial cover. That is SAVI's boundary decision,
  // signed off 2026-08-12, and this row follows it rather than forking it.)
  msavi: CANOPY(0.1, 0.2, 0.4, 0.6, 0.8),

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

  // ---- thermal (`landsat_c2_l2_st`) ---------------------------------------
  //
  // Three things separate these three tables from the ten above, and every one
  // of them breaks an assumption something in this file used to make:
  //
  //   1. `lst` carries a UNIT (°C) and a range of 0–60, not [-1, 1]. The
  //      fixed ±3 histogram clamp this module used to apply would have put
  //      every real pixel outside every interval — a transparent map, not a
  //      wrong colour. Hence `histogramFloor`/`histogramCeiling` per index.
  //   2. The reading is 100 m native resampled to 30 m. A block smaller than
  //      a hectare is a fraction of one pixel, so the block fill these classes
  //      drive is a farm-scale statement wearing a block-scale shape.
  //      `legend.thermalCaveat` says so on screen.
  //   3. Only `cwsi` has a published class table that transfers. The other
  //      two are descriptive bands, and both are in READ_RELATIVELY.

  // Surface temperature in °C, from `lwir11` via the Collection-2 scale
  // factors. Hot is bad, so the verdict ramp descends as the number climbs —
  // the same construction as `msi`.
  //
  // ⚠️ These cut points are DESCRIPTIVE, not agronomic thresholds. There is
  // no universal LST band table: what counts as hot depends on air
  // temperature, crop, growth stage and time of overpass (~10:20 local here),
  // and the physically meaningful quantity is canopy-MINUS-air, which is what
  // `cwsi` computes. They exist so a farm's own spread is visible — read
  // WHERE the field is hot relative to the rest of it, not which band it
  // lands in. Anchored so that the reference farm's observed 43–57 °C over
  // bare sand spans three classes rather than saturating in one.
  lst: [
    { max: 20, key: "cool", tone: "healthy", color: HEALTHY_HIGH },
    { max: 30, key: "mild", tone: "healthy", color: HEALTHY },
    { max: 38, key: "warm", tone: "watch", color: WATCH_HIGH },
    { max: 45, key: "hot", tone: "watch", color: WATCH },
    { max: 52, key: "veryHot", tone: "critical", color: CRITICAL_LOW },
    { max: Infinity, key: "extreme", tone: "critical", color: CRITICAL },
  ],

  // Crop water stress index, 0 (transpiring freely) to 1 (stomata shut).
  // Cut points are Idso's conventional reading — <0.2 unstressed, 0.2–0.4
  // mild, 0.4–0.6 moderate, 0.6–0.8 high, >0.8 severe — which is the one
  // published table here that genuinely transfers.
  //
  // ⚠️ But the INPUT does not, yet. The backend computes a simplified CWSI
  // against constant wet/dry bounds (CWSI_DT_WET_C/CWSI_DT_DRY_C) rather than
  // a crop-specific non-water-stressed baseline, and those constants have not
  // been calibrated for Egyptian mango. So the classes are right and the
  // values feeding them are provisional — which is why `cwsi` is in
  // READ_RELATIVELY despite having the best-founded table of the three.
  //
  // Over ground that is not transpiring at all the index pins at exactly
  // 1.000 everywhere, which is arithmetically correct and agronomically
  // empty. A uniformly `severe` farm is far more likely to be bare than dying.
  cwsi: [
    { max: 0.2, key: "unstressed", tone: "healthy", color: HEALTHY_HIGH },
    { max: 0.4, key: "mild", tone: "healthy", color: HEALTHY },
    { max: 0.6, key: "moderate", tone: "watch", color: WATCH },
    { max: 0.8, key: "high", tone: "critical", color: CRITICAL_LOW },
    { max: Infinity, key: "severe", tone: "critical", color: CRITICAL },
  ],

  // Soil moisture index, 0 on the fitted dry edge to 1 on the wet edge of the
  // LST–NDVI triangle. Reads the same direction as NDMI — low is dry — and
  // like NDMI its top class leaves the verdict ramp: the wet edge is where
  // over-irrigation and waterlogging live, which is a problem rather than the
  // best possible outcome.
  //
  // ⚠️ RELATIVE BY CONSTRUCTION, not merely uncalibrated. The edges are
  // fitted to the pixels of THIS scene over THIS AOI, so 0.4 on one farm and
  // 0.4 on another are not the same amount of water, and neither are 0.4 on
  // two different dates. And when the AOI's NDVI span is too narrow to fit a
  // triangle at all (SMI_MIN_NDVI_SPAN) the backend falls back to a plain LST
  // normalisation — still a valid ordering of wet to dry, but no longer the
  // index the name implies.
  smi: [
    { max: 0.2, key: "veryDry", tone: "critical", color: CRITICAL },
    { max: 0.4, key: "dry", tone: "critical", color: CRITICAL_LOW },
    { max: 0.6, key: "moderate", tone: "watch", color: WATCH },
    { max: 0.8, key: "moist", tone: "healthy", color: HEALTHY },
    { max: Infinity, key: "wet", tone: "watch", color: SATURATED },
  ],
};

/**
 * Indices whose classes should be read relatively, not as absolutes.
 *
 * NDRE because its published tables assume a different red-edge band than the
 * B5 we compute. All three thermal indices because each is provisional in its
 * own way: `lst`'s bands are descriptive rather than agronomic, `cwsi`'s wet
 * and dry bounds are uncalibrated constants, and `smi`'s edges are fitted per
 * scene so its scale is not even comparable between two dates of the same
 * farm.
 */
export const READ_RELATIVELY: ReadonlySet<AnyIndexCode> = new Set<AnyIndexCode>([
  "ndre",
  "lst",
  "cwsi",
  "smi",
]);

/**
 * Where our own class copy tells the reader to switch index, surface it on
 * that class's row. Only NDVI carries one today: above 0.80 NDVI saturates and
 * NDRE separates a good canopy from an excellent one. Do not invent entries —
 * add one only when the agronomy copy says so.
 */
export const CLASS_HINT: Partial<Record<AnyIndexCode, { classKey: string; suggest: string }>> = {
  ndvi: { classKey: "veryDense", suggest: "NDRE" },
};

/** Classes for an index, lowest first — the order the boundaries are defined in. */
export function classesFor(code: AnyIndexCode): IndexClass[] {
  return INDEX_CLASSES[code] ?? [];
}

/**
 * The class a reading falls in, or null when there is no reading. Mirrors the
 * inclusive-upper-bound convention above, so a value exactly on a boundary
 * belongs to the LOWER class — the same rule the tile colormap applies.
 */
export function classify(code: AnyIndexCode, value: number | null): IndexClass | null {
  if (value === null || !Number.isFinite(value)) return null;
  return classesFor(code).find((c) => value <= c.max) ?? null;
}

/**
 * Lower bound of a class — the previous class's `max`, or null for the first.
 * Kept as a function rather than a second field so the boundaries live in
 * exactly one place and cannot be edited into disagreement.
 */
export function lowerBound(code: AnyIndexCode, index: number): number | null {
  if (index <= 0) return null;
  return classesFor(code)[index - 1].max;
}

/**
 * Clamps for the open ends of an index's scale — where the first bin starts
 * and the last one stops.
 *
 * These are NOT cosmetic. They terminate both the histogram the legend counts
 * areas from and the interval colormap the tiles are painted with, and a pixel
 * outside every interval renders TRANSPARENT rather than in the nearest
 * colour. So a clamp that does not reach the data does not merely mis-colour
 * it — it erases it, and the legend then reports the erased ground as
 * unread.
 *
 * The ten optical indices are normalised differences bounded by [-1, 1],
 * except EVI/SAVI whose gain terms push slightly outside it over bright soil
 * and MSI which is an unbounded ratio — ±3 covers all of them with room to
 * spare, and that single pair of constants was the whole story until thermal.
 *
 * `lst` broke it. Degrees Celsius, not a ratio: every real pixel on the
 * reference farm reads 43–57, which is an order of magnitude past a ceiling
 * of 3. Hence a range per index rather than one for the module.
 */
const DEFAULT_HISTOGRAM_FLOOR = -3;
const DEFAULT_HISTOGRAM_CEILING = 3;

/**
 * Per-index overrides. Only the indices whose real values live outside the
 * default clamp appear here; `cwsi` and `smi` are 0–1 by construction and are
 * covered by it.
 *
 * The `lst` ceiling is well above the catalog's own 0–60 bound: the catalog
 * range is what the UI rescales for, while this is the "no pixel can be
 * outside this" backstop, and a bare desert surface at local noon is a
 * genuine 60+ in high summer. Clamping tight to the catalog would erase
 * exactly the hottest ground the reader is looking for.
 */
const HISTOGRAM_RANGE: Partial<Record<AnyIndexCode, { floor: number; ceiling: number }>> = {
  lst: { floor: -20, ceiling: 90 },
};

export function histogramFloor(code: AnyIndexCode): number {
  return HISTOGRAM_RANGE[code]?.floor ?? DEFAULT_HISTOGRAM_FLOOR;
}

export function histogramCeiling(code: AnyIndexCode): number {
  return HISTOGRAM_RANGE[code]?.ceiling ?? DEFAULT_HISTOGRAM_CEILING;
}

/**
 * Bin edges for a pixel histogram, ascending, as TiTiler's `histogram_bins`
 * wants them: N+1 edges for N classes.
 */
export function histogramBins(code: AnyIndexCode): number[] {
  const classes = classesFor(code);
  const edges = [histogramFloor(code)];
  const ceiling = histogramCeiling(code);
  for (const c of classes) edges.push(Number.isFinite(c.max) ? c.max : ceiling);
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
export function titilerColormap(code: AnyIndexCode): string {
  const classes = classesFor(code);
  const ceiling = histogramCeiling(code);
  const intervals = classes.map((c, i) => {
    const min = i === 0 ? histogramFloor(code) : classes[i - 1].max;
    const max = Number.isFinite(c.max) ? c.max : ceiling;
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
