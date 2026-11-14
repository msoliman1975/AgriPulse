"""The reference values a crop path may set, with their units and bounds.

Defined here rather than in the database so a row can never carry a key no
reader knows, or a unit a reader does not expect. Adding a key is a code
change with its own review, which is the point: it widens what trees can
read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Group = Literal["salinity", "yield", "spacing"]


@dataclass(frozen=True, slots=True)
class ReferenceKey:
    key: str
    group: Group
    unit: str
    lower: float
    upper: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "group": self.group,
            "unit": self.unit,
            "lower": self.lower,
            "upper": self.upper,
        }


KEYS: tuple[ReferenceKey, ...] = (
    # Salt tolerance (D18): FAO's threshold and slope, and irrigation water.
    ReferenceKey("soil_ece_threshold_ds_m", "salinity", "dS/m", 0, 100),
    ReferenceKey("yield_loss_pct_per_ds_m", "salinity", "%/(dS/m)", 0, 100),
    ReferenceKey("irrigation_water_ecw_max_ds_m", "salinity", "dS/m", 0, 100),
    ReferenceKey("leaching_requirement_pct", "salinity", "%", 0, 100),
    # Expected yield and load (D23).
    ReferenceKey("yield_per_plant_kg", "yield", "kg/plant", 0, 100000),
    ReferenceKey("fruit_weight_g", "yield", "g", 0, 100000),
    ReferenceKey("bunches_per_plant", "yield", "count", 0, 10000),
    # Spacing (D23). Plants per hectare follows from these two.
    ReferenceKey("row_spacing_m", "spacing", "m", 0, 1000),
    ReferenceKey("in_row_spacing_m", "spacing", "m", 0, 1000),
)

BY_KEY: dict[str, ReferenceKey] = {k.key: k for k in KEYS}


def resolve(crop_path: str, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every key ``crop_path`` reads, shallowest path first, deepest winning.

    ``rows`` are rows of any paths; only ``crop_path`` and its ancestors
    count. Each resolved entry says which path it came from, so the screen
    can say "inherited from date_palm".
    """
    segments = [s for s in crop_path.split(".") if s]
    chain = [".".join(segments[: i + 1]) for i in range(len(segments))]
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_path.setdefault(row["crop_path"], []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for path in chain:
        for row in by_path.get(path, []):
            if row["key"] in BY_KEY:
                out[row["key"]] = {
                    "value": row["value"],
                    "value_min": row["value_min"],
                    "value_max": row["value_max"],
                    "note": row.get("note"),
                    "from_path": path,
                }
    return out


def plants_per_ha(resolved: dict[str, dict[str, Any]]) -> float | None:
    """10,000 m² over the area each plant takes, when both spacings are single values."""
    row = (resolved.get("row_spacing_m") or {}).get("value")
    in_row = (resolved.get("in_row_spacing_m") or {}).get("value")
    if not row or not in_row:
        return None
    return round(10000 / (float(row) * float(in_row)), 1)
