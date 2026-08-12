"""Pure weather-driven disease/pest risk models (PR-R1, mango V1).

Each model is a side-effect-free function

    (window: Sequence[RiskWeatherDay], ctx: RiskBlockContext) -> RiskScore | None

that integrates *favorable-condition exposure* over a trailing daily window
into a 0-100 pressure score, modulated by the block's growth stage, then bands
it low/moderate/high. ``None`` means "cannot assess" (no day in the window
carried the signals the model needs) — distinct from a real zero score.

**Coefficient provenance (proposal §10 Q2).** The seed sheet
(``weather indices(Sheet1).csv``) is purely *qualitative* ("heat stress
predisposes mango to powdery mildew"; "heavy rain increases anthracnose").
There is no validated infection model for Egyptian orchards yet, so the
numeric bands below are **rule-of-thumb values transcribed from the extension
literature and deliberately tunable** — they live as named module constants,
not magic numbers, so an agronomist can refine them without touching logic.
The architecture (registry + accumulation shape) is the contract; the
coefficients are V1 placeholders.

Resolution note: the models read *daily* aggregates (mean temp, daily mean RH,
daily rain) plus, where available, hourly-derived leaf wetness.

The leaf-wetness upgrade this docstring used to describe as future work has
landed: ``RiskWeatherDay.leaf_wetness_hours`` carries the NHRH90 hour count and
the two foliar models now prefer it over the daily-mean-RH proxy. They read it
in OPPOSITE directions, which is the whole point of having it — prolonged wetness
drives anthracnose infection and suppresses powdery mildew, and a daily mean RH
could not distinguish the two. The proxy remains as the fallback for days
projected before the index existed, so a `None` means "not measured", never "dry".
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.modules.weather.risk.types import (
    RiskBlockContext,
    RiskLevel,
    RiskScore,
    RiskWeatherDay,
)

# --- Banding (global defaults; proposal §10 Q4) ----------------------------
# A score >= _HIGH_CUTOFF is "high", >= _MODERATE_CUTOFF "moderate", else
# "low". Global for V1; a per-pathogen override can move to the catalog later.
_MODERATE_CUTOFF = 40
_HIGH_CUTOFF = 70

# Stage modulation: when we positively know the block is in a stage the
# pathogen does NOT attack, damp the weather signal by this factor. An unknown
# stage keeps the full weather-only signal (graceful degradation), so risk is
# never *suppressed* just because phenology hasn't advanced the block yet.
_OFF_STAGE_FACTOR = Decimal("0.5")
# Fruit fly damage requires fruit on the tree, so its off-window damping is
# stronger than the foliar diseases'.
_FRUIT_OFF_STAGE_FACTOR = Decimal("0.25")


def _band(score: int) -> RiskLevel:
    if score >= _HIGH_CUTOFF:
        return RiskLevel.high
    if score >= _MODERATE_CUTOFF:
        return RiskLevel.moderate
    return RiskLevel.low


def _triangular(value: Decimal, lo: Decimal, hi: Decimal, tol: Decimal) -> Decimal:
    """Membership in [0,1]: 1.0 across [lo,hi], linear falloff to 0 over ``tol``.

    A plateau-with-shoulders favourability curve for a temperature band.
    """
    if lo <= value <= hi:
        return Decimal(1)
    dist = lo - value if value < lo else value - hi
    if dist >= tol:
        return Decimal(0)
    return Decimal(1) - dist / tol


def _stage_factor(stage: str | None, susceptible: frozenset[str], *, off: Decimal) -> Decimal:
    """1.0 in a susceptible stage or when stage is unknown; ``off`` otherwise."""
    if stage is None:
        return Decimal(1)
    return Decimal(1) if stage in susceptible else off


def _score(base: Decimal, stage_factor: Decimal) -> int:
    """Scale a [0,1] favourability by the stage factor onto an int 0-100."""
    raw = (base * stage_factor * Decimal(100)).to_integral_value(rounding="ROUND_HALF_UP")
    return max(0, min(100, int(raw)))


def _f2(value: Decimal) -> str:
    """Format a Decimal to 2 dp for the ``inputs`` jsonb (string convention)."""
    return str(value.quantize(Decimal("0.01")))


# ===========================================================================
# Powdery mildew — Oidium mangiferae
# ===========================================================================
# Conidia germinate best at moderate-warm temperatures with high humidity, but
# free water on the leaf SUPPRESSES the disease (rain washes conidia off). So
# pressure accumulates on warm-humid-*dry* days, worst through panicle
# emergence and flowering. Refs: CABI/extension guidance for mango powdery
# mildew. All thresholds tunable.
_PM_TEMP_LO = Decimal("20")
_PM_TEMP_HI = Decimal("27")
_PM_TEMP_TOL = Decimal("6")
_PM_RH_MIN = Decimal("60")
_PM_RAIN_SUPPRESS_MM = Decimal("2")  # a day wetter than this washes spores off
# Free water suppresses this pathogen, so leaf wetness works the OPPOSITE way
# here to anthracnose: a long wet spell is protective, not favourable. Set
# above the anthracnose infection threshold so a moderately damp night still
# counts as mildew-favourable while a genuinely soaking one does not.
_PM_WET_SUPPRESS_HOURS = Decimal("10")
_PM_SUSCEPTIBLE_STAGES = frozenset({"pre_flowering", "flowering", "fruit_set"})


def powdery_mildew(window: Sequence[RiskWeatherDay], ctx: RiskBlockContext) -> RiskScore | None:
    favs: list[Decimal] = []
    favorable_days = 0
    for d in window:
        if d.temp_mean_c is None or d.humidity_mean_pct is None:
            continue  # needs both temp and humidity to assess this day
        temp_f = _triangular(d.temp_mean_c, _PM_TEMP_LO, _PM_TEMP_HI, _PM_TEMP_TOL)
        humid_ok = d.humidity_mean_pct >= _PM_RH_MIN
        rain = d.precip_mm if d.precip_mm is not None else Decimal(0)
        # Humid air favours this pathogen; standing water on the leaf does
        # not. Rain was the only proxy for that until leaf wetness existed,
        # and it missed the case that matters most in an Egyptian orchard —
        # a heavy dew night with no rain at all.
        soaked = d.leaf_wetness_hours is not None and d.leaf_wetness_hours >= _PM_WET_SUPPRESS_HOURS
        dry_ok = rain < _PM_RAIN_SUPPRESS_MM and not soaked
        day_fav = temp_f if (humid_ok and dry_ok) else Decimal(0)
        favs.append(day_fav)
        if day_fav >= Decimal("0.5"):
            favorable_days += 1
    if not favs:
        return None
    base = sum(favs, start=Decimal(0)) / Decimal(len(favs))
    stage_factor = _stage_factor(ctx.growth_stage, _PM_SUSCEPTIBLE_STAGES, off=_OFF_STAGE_FACTOR)
    score = _score(base, stage_factor)
    return RiskScore(
        risk_code="powdery_mildew",
        score=score,
        level=_band(score),
        inputs={
            "window_days": str(len(favs)),
            "favorable_days": str(favorable_days),
            "mean_favorability": _f2(base),
            "stage_factor": _f2(stage_factor),
        },
    )


# ===========================================================================
# Anthracnose — Colletotrichum gloeosporioides
# ===========================================================================
# The mirror image of powdery mildew: infection needs warm temperatures AND
# prolonged leaf wetness (rain or near-saturated air). Pressure accumulates on
# warm-WET days through flowering and fruit development (latent infections).
_AN_TEMP_LO = Decimal("24")
_AN_TEMP_HI = Decimal("30")
_AN_TEMP_TOL = Decimal("7")
_AN_WET_RH = Decimal("90")
_AN_WET_RAIN_MM = Decimal("1")  # measurable rain == leaf wetness
# Hours of leaf wetness that count as a genuine infection period. Most foliar
# pathogens need a sustained wet spell rather than a damp moment; 6h is the
# low end of the range the literature reports for Colletotrichum.
_AN_WET_HOURS = Decimal("6")
_AN_SUSCEPTIBLE_STAGES = frozenset({"flowering", "fruit_set", "fruit_development"})


def anthracnose(window: Sequence[RiskWeatherDay], ctx: RiskBlockContext) -> RiskScore | None:
    favs: list[Decimal] = []
    wet_days = 0
    measured_wetness_days = 0
    for d in window:
        if d.temp_mean_c is None:
            continue
        temp_f = _triangular(d.temp_mean_c, _AN_TEMP_LO, _AN_TEMP_HI, _AN_TEMP_TOL)
        rain = d.precip_mm if d.precip_mm is not None else Decimal(0)
        # Prefer measured leaf-wetness hours; fall back to the daily-mean-RH
        # proxy for days projected before that index existed. The two disagree
        # in the case the proxy was always weakest at: a day averaging 70% RH
        # can still hold 10 saturated hours overnight, and the mean hides it.
        if d.leaf_wetness_hours is not None:
            wet = d.leaf_wetness_hours >= _AN_WET_HOURS
            measured_wetness_days += 1
        else:
            rh = d.humidity_mean_pct
            wet = rh is not None and rh >= _AN_WET_RH
        wet = wet or rain >= _AN_WET_RAIN_MM
        day_fav = temp_f if wet else Decimal(0)
        favs.append(day_fav)
        if wet:
            wet_days += 1
    if not favs:
        return None
    base = sum(favs, start=Decimal(0)) / Decimal(len(favs))
    stage_factor = _stage_factor(ctx.growth_stage, _AN_SUSCEPTIBLE_STAGES, off=_OFF_STAGE_FACTOR)
    score = _score(base, stage_factor)
    return RiskScore(
        risk_code="anthracnose",
        score=score,
        level=_band(score),
        inputs={
            "window_days": str(len(favs)),
            "wet_days": str(wet_days),
            # Says how much of the verdict rests on measured wetness rather
            # than the RH proxy — otherwise a score built entirely on the
            # fallback is indistinguishable from one built on real hours.
            "measured_wetness_days": str(measured_wetness_days),
            "mean_favorability": _f2(base),
            "stage_factor": _f2(stage_factor),
        },
    )


# ===========================================================================
# Fruit fly — Bactrocera zonata / Ceratitis capitata
# ===========================================================================
# Population pressure tracks warm-humid degree-day accumulation above a
# development base (~13 C); dry air slows (but doesn't stop) development, so
# humidity is a multiplier, not a gate. Damage only matters when fruit is on
# the tree, so the fruiting window dominates via a strong off-stage damping.
_FF_BASE_C = Decimal("13")
# Degree-day sum (humidity-weighted) over the window that maps to a full score.
# ~15 effective DD/day * 14 d ~= 210 at the saturating end of normal summers.
_FF_DD_SATURATION = Decimal("210")
_FF_RH_BOOST_MIN = Decimal("50")
_FF_DRY_FACTOR = Decimal("0.6")  # humidity below the boost floor damps DD
_FF_SUSCEPTIBLE_STAGES = frozenset({"fruit_set", "fruit_development"})


def fruit_fly(window: Sequence[RiskWeatherDay], ctx: RiskBlockContext) -> RiskScore | None:
    accum = Decimal(0)
    usable = 0
    for d in window:
        if d.temp_mean_c is None:
            continue
        usable += 1
        dd = d.temp_mean_c - _FF_BASE_C
        if dd <= 0:
            continue
        rh = d.humidity_mean_pct
        humid_factor = Decimal(1) if (rh is not None and rh >= _FF_RH_BOOST_MIN) else _FF_DRY_FACTOR
        accum += dd * humid_factor
    if usable == 0:
        return None
    base = min(Decimal(1), accum / _FF_DD_SATURATION)
    stage_factor = _stage_factor(
        ctx.growth_stage, _FF_SUSCEPTIBLE_STAGES, off=_FRUIT_OFF_STAGE_FACTOR
    )
    score = _score(base, stage_factor)
    return RiskScore(
        risk_code="fruit_fly",
        score=score,
        level=_band(score),
        inputs={
            "window_days": str(usable),
            "degree_day_accum": _f2(accum),
            "dd_saturation": str(_FF_DD_SATURATION),
            "stage_factor": _f2(stage_factor),
        },
    )


__all__ = ["powdery_mildew", "anthracnose", "fruit_fly"]
