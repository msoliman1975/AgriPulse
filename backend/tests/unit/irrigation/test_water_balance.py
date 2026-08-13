"""Unit tests for the daily crop water balance (gap-audit finding D7).

Pure functions only — no DB, so these live under tests/unit rather than
beside the container-backed irrigation integration tests.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.irrigation.engine import (
    compute_water_balance,
    crop_et,
    resolve_kc,
)


def _balance(**kw):
    defaults = {
        "et0_mm": Decimal("6.00"),
        "precip_mm": Decimal("0"),
        "irrigation_mm": None,
        "growth_stage": "flowering",
        "phenology_stages": None,
    }
    return compute_water_balance(**{**defaults, **kw})


# --- ETc --------------------------------------------------------------------


def test_crop_et_scales_reference_demand_by_kc() -> None:
    assert crop_et(Decimal("1.10"), Decimal("6.00")) == Decimal("6.60")


def test_etc_differs_from_et0_which_is_the_whole_point_of_d7() -> None:
    """ET₀ is demand over reference grass; a flowering mango transpires more.

    `rain_et_balance` uses ET₀ directly, which understates crop demand — one
    of the two substitutions this table exists to correct.
    """
    et0 = Decimal("6.00")
    b = _balance(et0_mm=et0, growth_stage="flowering")
    assert b.et0_mm == et0
    assert b.etc_mm > et0
    assert b.etc_mm == Decimal("6.60")  # Kc 1.10 at flowering


# --- Kc provenance ----------------------------------------------------------


def test_kc_prefers_the_crop_catalog_over_the_builtin_default() -> None:
    stages = {"stages": [{"code": "flowering", "kc": "1.25"}]}
    resolved = resolve_kc(growth_stage="flowering", phenology_stages=stages)
    assert resolved.value == Decimal("1.25")
    assert resolved.source == "phenology"


def test_kc_falls_back_per_stage_then_generic() -> None:
    per_stage = resolve_kc(growth_stage="flowering", phenology_stages=None)
    assert per_stage.value == Decimal("1.10")
    assert per_stage.source == "stage_default"

    unknown = resolve_kc(growth_stage=None, phenology_stages=None)
    assert unknown.value == Decimal("0.85")
    assert unknown.source == "generic_default"


def test_balance_records_which_kc_tier_it_used() -> None:
    """A balance built on the generic 0.85 fallback and one built on a real
    per-stage value produce identical-looking numbers; only the provenance
    tells them apart afterwards."""
    assert _balance(growth_stage=None).kc_source == "generic_default"
    assert _balance(growth_stage="flowering").kc_source == "stage_default"
    assert (
        _balance(
            growth_stage="flowering",
            phenology_stages={"stages": [{"code": "flowering", "kc": 1.2}]},
        ).kc_source
        == "phenology"
    )


# --- The balance itself -----------------------------------------------------


def test_irrigation_closes_a_deficit_that_rain_alone_would_not() -> None:
    """The second D7 substitution: ignoring irrigation reports a deficit on a
    block that was in fact watered."""
    without = _balance(et0_mm=Decimal("6.00"), precip_mm=Decimal("0"))
    assert without.balance_mm == Decimal("-6.60")

    with_water = _balance(
        et0_mm=Decimal("6.00"),
        precip_mm=Decimal("0"),
        irrigation_mm=Decimal("8.00"),
    )
    assert with_water.balance_mm == Decimal("1.40")
    assert with_water.balance_mm > 0


def test_rain_and_irrigation_both_count_as_input() -> None:
    b = _balance(
        et0_mm=Decimal("5.00"),
        precip_mm=Decimal("3.00"),
        irrigation_mm=Decimal("4.00"),
        growth_stage="maturity",  # Kc 0.85 → ETc 4.25
    )
    assert b.etc_mm == Decimal("4.25")
    assert b.balance_mm == Decimal("2.75")  # 3 + 4 - 4.25


def test_unlogged_irrigation_is_distinguished_from_a_logged_zero() -> None:
    """Both contribute 0 mm — there is nothing else they could contribute —
    but conflating them would show every farm that does not use the irrigation
    module in permanent, fictitious drought."""
    unlogged = _balance(irrigation_mm=None)
    logged_none = _balance(irrigation_mm=Decimal("0"))

    assert unlogged.irrigation_mm == logged_none.irrigation_mm == Decimal("0")
    assert unlogged.balance_mm == logged_none.balance_mm
    assert unlogged.irrigation_logged is False
    assert logged_none.irrigation_logged is True


def test_missing_precipitation_counts_as_no_rain() -> None:
    assert _balance(precip_mm=None).precip_mm == Decimal("0")


def test_growth_stage_is_carried_through_for_the_reader() -> None:
    assert _balance(growth_stage="fruit_set").growth_stage == "fruit_set"
    assert _balance(growth_stage=None).growth_stage is None
