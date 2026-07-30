"""Per-key value constraints for the three-tier settings resolver.

``platform_defaults`` only constrains ``value_schema`` (a JSON type) and
``category``. That let an operator save `imagery.cloud_cover_threshold_pct
= 5000` or `weather.default_cadence_hours = 0` — values the tiers *below*
reject outright, since `farm_imagery_overrides` CHECKs 0..100 and
`farm_weather_overrides` CHECKs `> 0`. The platform fallback could hold a
value no lower tier would accept.

This module is the single source of truth for what each key may hold. It
is applied on every write path — the platform-defaults editor, the tenant
Integrations pages, and the platform-side per-tenant editor — and is
serialised into the ``GET /api/v1/admin/defaults`` response so the browser
can enforce the same bounds before a round-trip.

Keys absent from ``CONSTRAINTS`` are type-checked against ``value_schema``
and otherwise unconstrained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KeyConstraint:
    """Bounds for one settings key, on top of its ``value_schema``."""

    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    #: Whether JSON ``null`` is a meaningful value (e.g. "inherit / unset").
    nullable: bool = False
    #: Reject non-integral numbers. Only meaningful for value_schema=number.
    integer_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON shape sent to the browser alongside each default."""
        out: dict[str, Any] = {}
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        if self.choices is not None:
            out["choices"] = list(self.choices)
        if self.nullable:
            out["nullable"] = True
        if self.integer_only:
            out["integer_only"] = True
        return out


# Bounds mirror the CHECK constraints on the lower tiers so a platform
# value can always be written down into a Farm- or block-tier column.
CONSTRAINTS: dict[str, KeyConstraint] = {
    # `open_meteo` is the only registered provider — weather/tasks.py
    # dispatches on the literal and weather/snapshot.py's preference list
    # holds exactly one entry. Widening needs a code change either way.
    "weather.default_provider_code": KeyConstraint(choices=("open_meteo",)),
    # farm_weather_overrides CHECKs `cadence_hours > 0`; the integrations
    # payload caps at one week.
    "weather.default_cadence_hours": KeyConstraint(minimum=1, maximum=24 * 7, integer_only=True),
    # farm_imagery_overrides + imagery_aoi_subscriptions both CHECK 0..100.
    "imagery.cloud_cover_threshold_pct": KeyConstraint(minimum=0, maximum=100, integer_only=True),
    # Std-devs below the block mean. 0 would flag every cell; beyond ~10 the
    # detector can never fire on a real distribution.
    "grid.anomaly_z_threshold": KeyConstraint(minimum=0.1, maximum=10.0),
}


def constraint_for(key: str) -> KeyConstraint | None:
    return CONSTRAINTS.get(key)


def describe(key: str) -> dict[str, Any] | None:
    """Serialisable constraint for `key`, or None when unconstrained."""
    c = CONSTRAINTS.get(key)
    if c is None:
        return None
    described = c.as_dict()
    return described or None
