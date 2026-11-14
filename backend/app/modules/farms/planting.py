"""Plant densities derived from a block's planting layout (D23).

Two numbers, because they answer different questions. Density from spacing
is what the layout was meant to hold (10,000 m² over the area each plant
takes); density from the count is what the block actually holds over its
mapped area. A large gap between them means missing plants, a mapped area
that includes roads or margins, or a spacing recorded wrongly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_M2_PER_HA = Decimal(10000)
_ONE_PLACE = Decimal("0.1")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def planting_densities(
    *,
    row_spacing_m: Any,
    in_row_spacing_m: Any,
    plant_count: int | None,
    area_m2: Any,
) -> dict[str, Decimal | None]:
    """``plants_per_ha_from_spacing`` and ``plants_per_ha_from_count``, one decimal place.

    Each is ``None`` when its inputs are missing or not positive.
    """
    row = _decimal(row_spacing_m)
    in_row = _decimal(in_row_spacing_m)
    area = _decimal(area_m2)

    from_spacing: Decimal | None = None
    if row is not None and in_row is not None and row > 0 and in_row > 0:
        from_spacing = (_M2_PER_HA / (row * in_row)).quantize(_ONE_PLACE, ROUND_HALF_UP)

    from_count: Decimal | None = None
    if plant_count is not None and area is not None and area > 0:
        from_count = (Decimal(plant_count) * _M2_PER_HA / area).quantize(_ONE_PLACE, ROUND_HALF_UP)

    return {
        "plants_per_ha_from_spacing": from_spacing,
        "plants_per_ha_from_count": from_count,
    }
