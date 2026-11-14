"""Plant densities derived from a block's planting layout (D23)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.farms.planting import planting_densities


def test_the_manuals_medjool_layouts() -> None:
    # Manual 1.7, 3.1 #7: 10 x 8 m or 9 x 9 m.
    ten_by_eight = planting_densities(
        row_spacing_m=Decimal("10"), in_row_spacing_m=Decimal("8"), plant_count=None, area_m2=None
    )
    assert ten_by_eight["plants_per_ha_from_spacing"] == Decimal("125.0")
    nine_by_nine = planting_densities(
        row_spacing_m=9, in_row_spacing_m=9, plant_count=None, area_m2=None
    )
    assert nine_by_nine["plants_per_ha_from_spacing"] == Decimal("123.5")


def test_density_from_the_count_over_the_mapped_area() -> None:
    out = planting_densities(
        row_spacing_m=None,
        in_row_spacing_m=None,
        plant_count=250,
        area_m2=Decimal("20000"),
    )
    assert out["plants_per_ha_from_count"] == Decimal("125.0")
    assert out["plants_per_ha_from_spacing"] is None


def test_missing_or_non_positive_inputs_give_none() -> None:
    for kwargs in (
        {"row_spacing_m": 10, "in_row_spacing_m": None, "plant_count": None, "area_m2": None},
        {"row_spacing_m": 0, "in_row_spacing_m": 8, "plant_count": None, "area_m2": None},
        {"row_spacing_m": None, "in_row_spacing_m": None, "plant_count": 10, "area_m2": 0},
        {"row_spacing_m": None, "in_row_spacing_m": None, "plant_count": 10, "area_m2": None},
    ):
        out = planting_densities(**kwargs)  # type: ignore[arg-type]
        assert out == {"plants_per_ha_from_spacing": None, "plants_per_ha_from_count": None}
