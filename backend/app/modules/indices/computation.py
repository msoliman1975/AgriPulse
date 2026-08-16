"""Pure-numpy index formulas + aggregate statistics.

This module has no I/O dependencies — every function takes ndarrays
and returns ndarrays or scalars. Rasterio reads, AOI rasterization,
and S3 writes live in the Celery task that calls these functions
(``app.modules.imagery.tasks.compute_indices``). Keeping the math
pure means the unit tests can pass tiny hand-crafted fixtures and
assert exact expected values.

Ten standard indices per ARCHITECTURE.md § 9 — the original six, plus
``ndmi`` (added for the KB water-stress catalog), plus ``bsi`` and ``msi``
(added from the indices-guide gap audit), plus ``msavi`` (the self-adjusting
successor to ``savi``). Their canonical formulas are seeded in
``public.indices_catalog`` (migration 0008 for the first six, 0027 for
``ndmi``, 0061 for ``bsi``/``msi``, 0068 for ``msavi``); we restate them
here as actual numpy operations.

Plus three **thermal** indices — ``lst``, ``cwsi``, ``smi`` — which come
from a different product (`landsat_c2_l2_st`, public migration 0066) with
a disjoint band set. They are kept in their own tuple and reached through
``compute_indices_for_product``; ``compute_all_indices`` still means the
Sentinel-2 set and would raise KeyError on Landsat bands.

Note that not every index is a normalized difference bounded to [-1, 1]:
``msi`` is a plain band *ratio* in roughly [0, 3], and it runs the
opposite way to the rest (higher = more stress); ``lst`` is a physical
temperature in **degrees Celsius**, the only index here with a unit at
all. Anything downstream that assumes a [-1, 1] range or a "higher is
healthier" polarity has to special-case both — see
``indices_catalog.value_min/value_max`` and the frontend's ``INDEX_BANDS``
tone table.

Spectral inputs are FLOAT32 surface-reflectance values in 0..1 (both
adapters normalise to that range — see ``providers/sentinel_hub.py`` and
``providers/landsat_pc.py``). The one exception is ``lwir11``, which
arrives in **kelvin**. Division-by-zero is masked rather than raising:
the resulting index pixel becomes ``NaN`` and is dropped from the
valid-pixel count downstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Band names match `public.imagery_products.bands` for s2_l2a (PR-A).
# Use a Literal-ish constant rather than an enum to keep the math API
# string-based (matches `indices_catalog.code`).
BAND_BLUE = "blue"
BAND_GREEN = "green"
BAND_RED = "red"
BAND_RED_EDGE_1 = "red_edge_1"
BAND_NIR = "nir"
BAND_SWIR1 = "swir1"
BAND_SWIR2 = "swir2"

S2_L2A_BAND_ORDER: tuple[str, ...] = (
    BAND_BLUE,
    BAND_GREEN,
    BAND_RED,
    BAND_RED_EDGE_1,
    BAND_NIR,
    BAND_SWIR1,
    BAND_SWIR2,
)

# Identifies the code that produced a stored aggregate row, recorded on every
# `indices_calc_runs` row (tenant migration 0060).
#
# **Bump this whenever anything below changes the numbers**: a formula, the
# band set a formula consumes, or `S2_SCL_MASKED_CLASSES`. It lives in this
# module rather than in the pipeline task so it sits next to the maths it
# versions — a formula edit and a forgotten bump are then adjacent lines in
# the same diff.
#
# Without it, two methodologies can share a trend line indistinguishably. The
# pre-#288 rows are the worked example: they were averaged without SCL
# masking, so their means run high, and nothing in the database says so.
#
# NOT bumped when a *new* index code is added, only when an existing one's
# numbers move. Adding `bsi`/`msi` left every prior series byte-identical, so
# a bump would have announced a methodology break that did not happen and
# split seven healthy trend lines in two. `ndmi` (0027) set this precedent.
#
# Adding `lst`/`cwsi`/`smi` and the `landsat_qa_pixel_v1` ruleset followed the
# same reasoning and did NOT bump: they are a new product's index set on a new
# band set, reached through a separate code path, and no Sentinel-2 formula,
# band set or masking rule changed. Every existing series is byte-identical,
# so a bump would have split nine healthy trend lines for a methodology break
# that did not happen.
CALC_VERSION = "idx-2026.08"

# Names the SCL class set below, so a stored row records *which* masking rules
# ran rather than just that some did. `PRODUCT_MASK_RULESETS` maps each product
# to its own name — Landsat's quality band is a bitmask, not a class enum, so
# it needs a different ruleset rather than a different class list.
MASK_RULESET = "s2_scl_v1"

# Indices supported today. Order matches the catalog's seeded rows.
#
# ``ndmi`` (KB P2 prerequisite) was added after the original six — it is the
# leaf/canopy-moisture index the water-stress catalog needs, distinct from
# McFeeters ``ndwi`` (surface water). ``bsi`` and ``msi`` came from the
# indices-guide gap audit: ``bsi`` measures exposed ground between trees,
# which nothing else here measures; ``msi`` is a second view of the same
# moisture signal as ``ndmi`` on an unbounded, inverted scale. ``msavi``
# (0068) is ``savi`` with its soil factor solved per pixel instead of pinned
# at L = 0.5.
#
# This tuple is mirrored in the frontend (``api/indices.ts``, ``conditionEdit
# .ts``, ``MAP_INDEX_ORDER``) and the pairing is enforced by
# ``tests/unit/shared/test_index_codes_frontend_parity.py``.
STANDARD_INDEX_CODES: tuple[str, ...] = (
    "ndvi",
    "ndwi",
    "evi",
    "savi",
    "ndre",
    "gndvi",
    "ndmi",
    "bsi",
    "msi",
    "msavi",
)


# Sentinel-2 L2A Scene Classification (SCL) values treated as "not usable"
# for index aggregation: 0 no-data, 1 saturated/defective, 3 cloud shadow,
# 8 cloud medium-prob, 9 cloud high-prob, 10 thin cirrus, 11 snow/ice. Kept
# as clear land/water: 2 dark-area pixels, 4 vegetation, 5 bare soil,
# 6 water, 7 unclassified. Mirrors the evalscript used to validate against
# CDSE in docs/reports/index-accuracy-agrosina-2026-06-20.md.
S2_SCL_MASKED_CLASSES: tuple[int, ...] = (0, 1, 3, 8, 9, 10, 11)


def scl_cloud_mask(scl: NDArray[Any]) -> NDArray[np.bool_]:
    """Boolean mask, True where the SCL pixel is cloud/shadow/cirrus/snow/invalid.

    ``scl`` arrives as FLOAT32 (the multi-band COG is a single dtype), so the
    categorical codes are rounded back to ints before the membership test.
    """
    codes = np.rint(scl).astype(np.int16, copy=False)
    return np.isin(codes, S2_SCL_MASKED_CLASSES)


# --- Landsat thermal (product `landsat_c2_l2_st`) --------------------------

# Landsat's quality band is a *bitmask*, not a class enum — a different
# encoding from Sentinel-2's SCL, so `S2_SCL_MASKED_CLASSES` does not
# transfer and the two need separate rulesets. Collection-2 QA_PIXEL bits:
#
#   0 fill · 1 dilated cloud · 2 cirrus · 3 cloud · 4 cloud shadow
#   5 snow · 6 clear · 7 water · 8-15 per-class confidence pairs
#
# We drop bits 0-5 and keep water (bit 7), matching the SCL ruleset above
# which keeps class 6 (water) and class 2 (dark area).
#
# Measured over the Bashier Elkhier farm across 12 months (86 scenes,
# L8 43 + L9 43), sampling 22 of them and masking with the rules below:
#
#   farm >= 90% clear pixels ............... 19/22  (86%)
#   scene-level eo:cloud_cover <= 10% ...... 15/22  (68%)
#   median farm clear fraction ............. 100%
#
# The scene-level number is the one the study quoted as a usable-cadence
# floor, and it IS a floor: 4 of the 22 scenes carry >10% scene cloud yet
# are >=90% clear over the farm — one at 37.8% scene cloud is 100% clear
# here. `eo:cloud_cover` describes a 185 km scene, and our farm is 85 ha.
#
# Operational consequence: do NOT set a tight `cloud_cover_max_pct` on a
# thermal subscription. It discards scenes that are perfectly usable over
# the AOI, and it does not even protect against the converse — two
# sampled scenes with modest scene cloud (16.6%, 43.0%) were 0% clear
# over the farm. Per-pixel QA is the only honest filter.
LANDSAT_QA_MASKED_BITS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)

_LANDSAT_QA_MASK = sum(1 << bit for bit in LANDSAT_QA_MASKED_BITS)


def landsat_qa_pixel_mask(qa_pixel: NDArray[Any]) -> NDArray[np.bool_]:
    """Boolean mask, True where the Landsat QA_PIXEL bits say unusable.

    Like ``scl_cloud_mask``, ``qa_pixel`` arrives as FLOAT32 because the
    multi-band COG is a single dtype. uint16 is exactly representable in
    float32 (16 bits < 24-bit mantissa), so the bit patterns survive the
    round-trip and only need rounding back to an integer before masking.

    Note the polarity trap: bit 6 means *clear*, so testing "is any bit
    set" would mask every good pixel. Only bits 0-5 are failure bits.
    """
    codes = np.rint(qa_pixel).astype(np.uint16, copy=False)
    return (codes & np.uint16(_LANDSAT_QA_MASK)) != 0


# Absolute zero, for the Collection-2 Level-2 kelvin -> Celsius step.
_KELVIN_OFFSET = 273.15

# Canopy-to-air temperature difference bounds for the simplified CWSI.
#
# A canopy transpiring freely evaporatively cools itself *below* air
# temperature; one that has closed its stomata runs above it. These two
# numbers are the 0 and 1 ends of the scale.
#
# ⚠️ KNOWN DEBT: a rigorous CWSI derives the lower bound from a
# crop- and site-specific non-water-stressed baseline (Idso's VPD
# regression), not a constant. These are literature values for a
# well-coupled orchard canopy and have NOT been calibrated for Egyptian
# mango. Read the output as a relative signal over time, not an absolute
# stress threshold — the same species of debt the indices guide flags for
# LAI. Calibrating this is what would make CWSI actionable for irrigation
# volumes; until then it must not drive them.
CWSI_DT_WET_C = -2.0
CWSI_DT_DRY_C = 6.0

# The LST-NDVI triangle degenerates when every pixel has the same
# greenness: the dry and wet edges collapse onto each other and their
# fitted slopes become noise. A uniform mango block is exactly that case,
# so below this NDVI span `smi` falls back to a plain LST normalisation
# and says so rather than reporting a fitted edge it cannot support.
SMI_MIN_NDVI_SPAN = 0.20
SMI_NDVI_BINS = 20
SMI_MIN_BIN_PIXELS = 5

# Thermal indices, in catalog order. Kept separate from
# ``STANDARD_INDEX_CODES`` because they come from a different product with
# a different band set — a farm can carry both, or the optical one alone.
THERMAL_INDEX_CODES: tuple[str, ...] = ("lst", "cwsi", "smi")

# Which index set each product produces, and which masking rules its
# quality band follows. Dispatching on the product code keeps the
# pipeline honest: `compute_all_indices` would raise KeyError if handed a
# Landsat band set, and a stored aggregate row records *which* rules ran.
PRODUCT_INDEX_CODES: dict[str, tuple[str, ...]] = {
    "s2_l2a": STANDARD_INDEX_CODES,
    "landsat_c2_l2_st": THERMAL_INDEX_CODES,
}

PRODUCT_MASK_RULESETS: dict[str, str] = {
    "s2_l2a": MASK_RULESET,
    "landsat_c2_l2_st": "landsat_qa_pixel_v1",
}


# --- Aggregate result -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexAggregates:
    """Per-scene per-block per-index summary statistics.

    Fields map 1:1 to ``block_index_aggregates`` columns (data_model § 7.3).
    Decimal values are quantized to 4 fractional digits for `mean`/`min`/
    `max`/percentiles (matches `NUMERIC(7,4)`); pixel counts are int.
    """

    mean: Decimal | None
    min: Decimal | None
    max: Decimal | None
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    std_dev: Decimal | None
    valid_pixel_count: int
    total_pixel_count: int


# --- Index formulas --------------------------------------------------------


def _safe_divide(num: NDArray[Any], den: NDArray[Any]) -> NDArray[np.float32]:
    """Element-wise num/den, returning NaN where den == 0.

    Sentinel-2 L2A reflectance is non-negative; near-zero denominators
    happen at scene edges or shadowed pixels. We don't want those to
    raise or to produce ±inf — `NaN` is the standard sentinel for
    "no usable value" and downstream code already masks NaNs.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(den == 0, np.nan, num / den)
    return result.astype(np.float32, copy=False)


def ndvi(red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Vegetation Index: ``(NIR - RED) / (NIR + RED)``."""
    return _safe_divide(nir - red, nir + red)


def ndwi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Water Index (McFeeters): ``(GREEN - NIR) / (GREEN + NIR)``."""
    return _safe_divide(green - nir, green + nir)


def evi(blue: NDArray[Any], red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Enhanced Vegetation Index (MODIS coefficients):

    ``2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)``
    """
    num = 2.5 * (nir - red)
    den = nir + 6.0 * red - 7.5 * blue + 1.0
    return _safe_divide(num, den)


def savi(red: NDArray[Any], nir: NDArray[Any], soil_factor: float = 0.5) -> NDArray[np.float32]:
    """Soil-Adjusted Vegetation Index:

    ``(1 + L) * (NIR - RED) / (NIR + RED + L)`` where L=0.5 for moderate cover.
    """
    factor = np.float32(soil_factor)
    num = (1.0 + factor) * (nir - red)
    den = nir + red + factor
    return _safe_divide(num, den)


def msavi(red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Modified Soil-Adjusted Vegetation Index (MSAVI2, Qi et al. 1994):

    ``(2·NIR + 1 - sqrt((2·NIR + 1)² - 8·(NIR - RED))) / 2``

    ``savi`` above needs a soil factor chosen in advance, and L = 0.5 is only
    right for moderate cover: at low cover the correct L is nearer 1, at full
    canopy nearer 0. Picking one constant therefore under-corrects at one end
    of the season and over-corrects at the other. MSAVI2 is the closed-form
    solution for L at each pixel, folded back into the formula — so the soil
    correction tracks the cover it is correcting for, with nothing to tune.

    That makes it the more honest vigour reading exactly where our orchards
    live: wide tree spacing over bright Egyptian sand, where a large and
    *varying* fraction of every pixel is soil.

    Numerically it tracks ``savi`` closely (within a few hundredths over real
    reflectance) rather than ``ndvi``, which is why it shares SAVI's class
    boundaries downstream and not NDVI's.

    Note this is MSAVI**2**, the iteration-free form that is universally what
    "MSAVI" means in practice — not Qi's original L-from-NDVI·WDVI version,
    which needs a soil line fitted per site.

    The discriminant is ``(2·NIR - 1)² + 8·RED`` after expansion, so it is
    non-negative for any non-negative RED and the square root is real for
    every physical pixel. It is still guarded: L2A surface reflectance can
    come back very slightly negative over deep shadow, and ``sqrt`` of a
    negative would produce a NaN with no explanation attached.
    """
    two_nir_plus_one = 2.0 * nir + 1.0
    discriminant = two_nir_plus_one**2 - 8.0 * (nir - red)
    with np.errstate(invalid="ignore"):
        root = np.where(discriminant < 0, np.nan, np.sqrt(np.maximum(discriminant, 0.0)))
    return ((two_nir_plus_one - root) / 2.0).astype(np.float32, copy=False)


def ndre(red_edge_1: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Red Edge: ``(NIR - RED_EDGE) / (NIR + RED_EDGE)``."""
    return _safe_divide(nir - red_edge_1, nir + red_edge_1)


def gndvi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Green NDVI: ``(NIR - GREEN) / (NIR + GREEN)``."""
    return _safe_divide(nir - green, nir + green)


def ndmi(nir: NDArray[Any], swir1: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Moisture Index: ``(NIR - SWIR1) / (NIR + SWIR1)``.

    Tracks leaf / canopy **water content** (equivalent to NDII) and falls
    as tissue dries — an early water-stress signal. Not to be confused
    with ``ndwi`` above (McFeeters Green/NIR), which tracks open surface
    water, not leaf moisture.
    """
    return _safe_divide(nir - swir1, nir + swir1)


def bsi(
    blue: NDArray[Any],
    red: NDArray[Any],
    nir: NDArray[Any],
    swir1: NDArray[Any],
) -> NDArray[np.float32]:
    """Bare Soil Index:

    ``((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))``

    Weighs the two bands where soil reflects strongly (SWIR1, red) against
    the two where vegetation does (NIR, blue), so the value rises as bare
    ground takes over the pixel. This is the one index here that measures
    the *ground* rather than the canopy: it reads planting gaps, plant loss
    and poor establishment, which NDVI can only show as "less green".

    Normalized-difference form, so it shares the [-1, 1] range of ``ndvi``
    and friends. Positive = soil-dominated, negative = canopy-dominated.

    Rikimaru, Roy & Miyatake (2002), Int. J. Geoinformatics.
    """
    soil = swir1 + red
    veg = nir + blue
    return _safe_divide(soil - veg, soil + veg)


def msi(nir: NDArray[Any], swir1: NDArray[Any]) -> NDArray[np.float32]:
    """Moisture Stress Index: ``SWIR1 / NIR``.

    ⚠️ Two things about this one break the pattern every other function in
    this module follows, and both matter downstream:

    1. **It is a ratio, not a normalized difference.** The range is roughly
       [0, 3] for real surface reflectance, not [-1, 1]. Anything that
       clamps, rescales or colour-ramps on a [-1, 1] assumption will be
       wrong for ``msi`` rather than merely ugly.
    2. **It is inverted.** Higher means *more* water stress, where every
       other index here reads higher-is-healthier. A falling ``msi`` trend
       is good news; a falling ``ndmi`` trend is bad news.

    Carries the same physical signal as ``ndmi`` — both contrast NIR against
    the SWIR band that liquid water absorbs — so it adds a familiar name and
    an unbounded scale rather than independent information. The two are a
    monotone transform of each other: ``ndmi == (1 - msi) / (1 + msi)``.

    Rock et al. (1986), ERIM 4th Thematic Conference.
    """
    return _safe_divide(swir1, nir)


# --- Thermal index formulas ------------------------------------------------


def lst(lwir11: NDArray[Any]) -> NDArray[np.float32]:
    """Land Surface Temperature in **degrees Celsius**.

    ``lwir11`` arrives in kelvin: the provider adapter has already applied
    Collection-2's ``DN * 0.00341802 + 149.0`` and turned fill pixels into
    NaN, so this is only the unit conversion.

    ⚠️ This is the first index in this module that is not dimensionless.
    Everything that assumes a [-1, 1] range or a "higher is healthier"
    polarity is wrong for it on both counts — see ``msi`` for the other
    exception, and ``indices_catalog.value_min/value_max``.
    """
    values = lwir11.astype(np.float32, copy=False)
    return (values - np.float32(_KELVIN_OFFSET)).astype(np.float32, copy=False)


def cwsi(lst_c: NDArray[Any], air_temp_c: float) -> NDArray[np.float32]:
    """Crop Water Stress Index, simplified temperature-difference form.

    ``(dT - dT_wet) / (dT_dry - dT_wet)`` where ``dT = LST - Tair``.

    0 is a freely transpiring canopy, 1 a fully stressed one. Clipped to
    that range: the bounds are literature constants, so a pixel outside
    them means the constants are off for this site, not that stress is
    negative.

    ``air_temp_c`` is a scalar for the whole AOI — the hourly weather feed
    interpolated to the satellite overpass minute. Using air temperature
    rather than the AOI's own spread is what keeps this independent of
    ``smi``: normalise the AOI twice and the two indices are just each
    other's inverse, carrying no separate information.

    See ``CWSI_DT_WET_C`` for the calibration debt this carries.
    """
    delta = lst_c.astype(np.float32, copy=False) - np.float32(air_temp_c)
    span = np.float32(CWSI_DT_DRY_C - CWSI_DT_WET_C)
    raw = (delta - np.float32(CWSI_DT_WET_C)) / span
    return np.clip(raw, 0.0, 1.0).astype(np.float32, copy=False)


def smi(lst_c: NDArray[Any], ndvi_values: NDArray[Any]) -> NDArray[np.float32]:
    """Soil Moisture Index from the LST-NDVI triangle.

    For a given greenness, wetter ground runs cooler, so the spread of
    temperature at equal NDVI maps to moisture. We fit a dry edge (hottest
    pixel per NDVI bin) and a wet edge (coolest), then place each pixel
    between them: 1 on the wet edge, 0 on the dry one.

    ``ndvi_values`` MUST come from the same scene as ``lst_c`` — the
    Landsat red/nir08 bands, not our 10 m Sentinel-2 stack. The triangle
    is only valid when both surfaces are the same ground at the same
    moment; pairing a morning Landsat LST with a different day's S2 NDVI
    silently fits edges to two unrelated surfaces.

    Falls back to a plain LST normalisation when the NDVI span is too
    narrow to define edges (see ``SMI_MIN_NDVI_SPAN``) — the usual case
    for a uniform block, where a fitted slope would be pure noise.
    """
    temps = lst_c.astype(np.float32, copy=False)
    greens = ndvi_values.astype(np.float32, copy=False)
    usable = np.isfinite(temps) & np.isfinite(greens)
    if not usable.any():
        return np.full(temps.shape, np.float32("nan"), dtype=np.float32)

    edges = _fit_triangle_edges(temps[usable], greens[usable])
    if edges is None:
        return _normalise_inverted(temps, usable)

    (dry_intercept, dry_slope), (wet_intercept, wet_slope) = edges
    dry = dry_intercept + dry_slope * greens
    wet = wet_intercept + wet_slope * greens
    span = dry - wet
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(span > 0, (dry - temps) / span, np.nan)
    return np.clip(raw, 0.0, 1.0).astype(np.float32, copy=False)


def _fit_triangle_edges(
    temps: NDArray[np.float32], greens: NDArray[np.float32]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Least-squares dry/wet edges over NDVI bins, or None if degenerate.

    Returns ``((dry_intercept, dry_slope), (wet_intercept, wet_slope))``.
    None means the triangle could not be supported — too narrow an NDVI
    span, or too few populated bins to fit a line through.
    """
    ndvi_min = float(greens.min())
    ndvi_max = float(greens.max())
    if ndvi_max - ndvi_min < SMI_MIN_NDVI_SPAN:
        return None

    bin_edges = np.linspace(ndvi_min, ndvi_max, SMI_NDVI_BINS + 1)
    # `- 1` maps the value back to a 0-based bin; `clip` folds the
    # rightmost edge into the last bin instead of its own empty one.
    membership = np.clip(np.digitize(greens, bin_edges) - 1, 0, SMI_NDVI_BINS - 1)

    centres: list[float] = []
    hottest: list[float] = []
    coolest: list[float] = []
    for index in range(SMI_NDVI_BINS):
        in_bin = membership == index
        if int(np.count_nonzero(in_bin)) < SMI_MIN_BIN_PIXELS:
            continue
        centres.append(float((bin_edges[index] + bin_edges[index + 1]) / 2.0))
        hottest.append(float(temps[in_bin].max()))
        coolest.append(float(temps[in_bin].min()))

    # Two points minimum for a line, and `polyfit` on two identical NDVI
    # centres would be singular — the span check above rules that out.
    if len(centres) < 2:
        return None

    x = np.asarray(centres, dtype=np.float64)
    dry_slope, dry_intercept = np.polyfit(x, np.asarray(hottest, dtype=np.float64), 1)
    wet_slope, wet_intercept = np.polyfit(x, np.asarray(coolest, dtype=np.float64), 1)
    return (
        (float(dry_intercept), float(dry_slope)),
        (float(wet_intercept), float(wet_slope)),
    )


def _normalise_inverted(
    temps: NDArray[np.float32], usable: NDArray[np.bool_]
) -> NDArray[np.float32]:
    """Fallback SMI: place each pixel between the AOI's own hot/cold ends.

    Coarser than the triangle — it ignores the NDVI dependence entirely —
    but on a uniform canopy that dependence is what could not be measured
    in the first place.
    """
    values = temps[usable]
    hottest = float(values.max())
    coolest = float(values.min())
    if hottest - coolest <= 0:
        # Isothermal AOI: no moisture gradient to report.
        return np.where(usable, np.float32(0.5), np.float32("nan")).astype(np.float32)
    raw = (hottest - temps) / np.float32(hottest - coolest)
    return np.clip(np.where(usable, raw, np.nan), 0.0, 1.0).astype(np.float32, copy=False)


def compute_thermal_indices(
    bands: Mapping[str, NDArray[Any]],
    *,
    air_temp_c: float | None,
) -> dict[str, NDArray[np.float32]]:
    """Compute LST / CWSI / SMI from the Landsat C2 L2 band set.

    Missing bands raise KeyError — the caller hands in the full
    `landsat_c2_l2_st` band set.

    NDVI here is deliberately recomputed from the Landsat ``red`` and
    ``nir08`` bands rather than read from our Sentinel-2 series: SMI's
    triangle needs both surfaces to be the same ground at the same
    moment. The 10 m S2 NDVI stays the one we chart.

    ``air_temp_c is None`` means the weather feed had no usable reading
    to interpolate to the overpass minute. CWSI is then **omitted from
    the result** rather than returned as NaN or zero: a missing key
    leaves a gap in the series, which is true, where a fabricated value
    would read as "no stress". LST and SMI still compute — they need no
    weather — so one missing hour of weather does not cost the whole
    scene.
    """
    surface_c = lst(bands["lwir11"])
    landsat_ndvi = ndvi(bands["red"], bands["nir08"])
    computed: dict[str, NDArray[np.float32]] = {
        "lst": surface_c,
        "smi": smi(surface_c, landsat_ndvi),
    }
    if air_temp_c is not None:
        computed["cwsi"] = cwsi(surface_c, air_temp_c)
    # Catalog order, so downstream writes and charts stay stable.
    return {code: computed[code] for code in THERMAL_INDEX_CODES if code in computed}


def compute_indices_for_product(
    product_code: str,
    bands: Mapping[str, NDArray[Any]],
    *,
    air_temp_c: float | None = None,
) -> dict[str, NDArray[np.float32]]:
    """Compute the index set belonging to `product_code`.

    The pipeline is otherwise fully product-parameterised; this is the
    one place the maths itself differs, because the two products carry
    disjoint band sets.
    """
    if product_code == "s2_l2a":
        return compute_all_indices(bands)
    if product_code == "landsat_c2_l2_st":
        # `air_temp_c is None` costs CWSI only — see compute_thermal_indices.
        return compute_thermal_indices(bands, air_temp_c=air_temp_c)
    raise ValueError(f"No index set defined for product {product_code!r}")


def quality_band_mask(product_code: str, quality_band: NDArray[Any]) -> NDArray[np.bool_]:
    """Mask unusable pixels using the ruleset belonging to `product_code`.

    Sentinel-2's SCL is a class enum; Landsat's QA_PIXEL is a bitmask.
    Applying one product's rules to the other's quality band produces a
    plausible-looking mask that is entirely wrong, so this dispatches
    rather than guessing from the values.
    """
    if product_code == "s2_l2a":
        return scl_cloud_mask(quality_band)
    if product_code == "landsat_c2_l2_st":
        return landsat_qa_pixel_mask(quality_band)
    raise ValueError(f"No mask ruleset defined for product {product_code!r}")


def compute_all_indices(
    bands: Mapping[str, NDArray[Any]],
) -> dict[str, NDArray[np.float32]]:
    """Compute every standard index from a band → array mapping.

    Keys are exactly ``STANDARD_INDEX_CODES``. Missing bands raise KeyError —
    caller is responsible for handing in the full S2 L2A bandset.
    """
    return {
        "ndvi": ndvi(bands[BAND_RED], bands[BAND_NIR]),
        "ndwi": ndwi(bands[BAND_GREEN], bands[BAND_NIR]),
        "evi": evi(bands[BAND_BLUE], bands[BAND_RED], bands[BAND_NIR]),
        "savi": savi(bands[BAND_RED], bands[BAND_NIR]),
        "ndre": ndre(bands[BAND_RED_EDGE_1], bands[BAND_NIR]),
        "gndvi": gndvi(bands[BAND_GREEN], bands[BAND_NIR]),
        "ndmi": ndmi(bands[BAND_NIR], bands[BAND_SWIR1]),
        "bsi": bsi(
            bands[BAND_BLUE],
            bands[BAND_RED],
            bands[BAND_NIR],
            bands[BAND_SWIR1],
        ),
        "msi": msi(bands[BAND_NIR], bands[BAND_SWIR1]),
        "msavi": msavi(bands[BAND_RED], bands[BAND_NIR]),
    }


# --- Aggregation -----------------------------------------------------------


def compute_aggregates(
    index_array: NDArray[Any],
    valid_mask: NDArray[np.bool_],
) -> IndexAggregates:
    """Reduce one index raster to summary stats.

    ``valid_mask`` selects pixels inside the AOI with a usable
    reflectance value. Pixels outside the AOI or with NaN reflectance
    are excluded from `valid_pixel_count`. `total_pixel_count` is the
    AOI footprint (everything inside the polygon).

    With zero valid pixels every statistic is None — caller should
    still insert the row (the alert rule engine in PR-4 looks at
    `valid_pixel_pct` and decides what to do).
    """
    if index_array.shape != valid_mask.shape:
        raise ValueError(f"index/mask shape mismatch: {index_array.shape} vs {valid_mask.shape}")

    # `total_pixel_count` is the AOI footprint, i.e. the count of
    # pixels that COULD have been valid. We use the boolean mask shape
    # and count pixels inside the AOI; NaN pixels inside the AOI count
    # as "could-have-been-valid" but aren't.
    aoi_pixels = int(np.count_nonzero(valid_mask))
    if aoi_pixels == 0:
        return IndexAggregates(
            mean=None,
            min=None,
            max=None,
            p10=None,
            p50=None,
            p90=None,
            std_dev=None,
            valid_pixel_count=0,
            total_pixel_count=0,
        )

    # Drop NaNs from the masked subset. Both index_array and valid_mask
    # are shape-aligned 2D arrays.
    masked_values = index_array[valid_mask]
    finite = np.isfinite(masked_values)
    valid_pixel_count = int(np.count_nonzero(finite))
    if valid_pixel_count == 0:
        return IndexAggregates(
            mean=None,
            min=None,
            max=None,
            p10=None,
            p50=None,
            p90=None,
            std_dev=None,
            valid_pixel_count=0,
            total_pixel_count=aoi_pixels,
        )

    values = masked_values[finite].astype(np.float64, copy=False)
    percentiles = np.percentile(values, [10.0, 50.0, 90.0])
    return IndexAggregates(
        mean=_q4(float(values.mean())),
        min=_q4(float(values.min())),
        max=_q4(float(values.max())),
        p10=_q4(float(percentiles[0])),
        p50=_q4(float(percentiles[1])),
        p90=_q4(float(percentiles[2])),
        # ddof=0: population std-dev. The hypertable column is
        # documented as a per-scene std, not a sample estimate.
        std_dev=_q4(float(values.std(ddof=0))),
        valid_pixel_count=valid_pixel_count,
        total_pixel_count=aoi_pixels,
    )


def _q4(value: float) -> Decimal:
    """Quantize a Python float to NUMERIC(7,4) precision.

    Using Decimal here so the SQL parameter binding doesn't depend on
    floating-point rounding. The precision matches the column.
    """
    return Decimal(repr(value)).quantize(Decimal("0.0001"))
