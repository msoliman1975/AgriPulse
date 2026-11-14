"""Heat units configured per crop (D17).

The crop catalogue sets a GDD base and optional upper temperature on the crop
(``gdd_base_temp_c`` / ``gdd_upper_temp_c``), and, from public 0112, how heat
is counted (``gdd_method``) and from when (``gdd_start_kind`` /
``gdd_start_value``) on the crop, variety and strain. A tree reads the result
as ``{source: heat_units, key: total | today | days_since_start}``.

Computed per block at evaluation time from the farm's stored daily minimum and
maximum temperatures (``weather_derived_daily.temp_min_c`` / ``temp_max_c``);
no series is stored. Days missing either temperature are skipped.

Resolution:

* method and start inherit crop -> variety -> strain, deepest non-null wins,
  the way ``phenology_stages_override`` resolves. The start kind and value
  are one setting and travel together.
* the base and upper temperatures are the crop's own (they are not
  overridden per variety).
* a start date on the block's crop assignment (``block_crops.gdd_start_date``,
  tenant 0108) wins over the crop's start rule.

Fail closed: no crop, no method, no base, no start, a start in the future, or
no farm all give ``{}``, so every ``heat_units`` predicate is false.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.models import (
    BlockCrop,
    Crop,
    CropVariety,
    CropVarietyStrain,
    GrowthStageLog,
)
from app.modules.weather.snapshot import load_daily_temperatures
from app.shared import clock

GDD_METHODS: tuple[str, ...] = ("mean", "max", "min_max_cutoff")
GDD_START_KINDS: tuple[str, ...] = ("date", "planting", "stage")

_MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")
_ZERO = Decimal("0")
_TWO = Decimal("2")


@dataclass(frozen=True, slots=True)
class HeatUnitConfig:
    """The resolved setting for one crop path."""

    method: str | None
    start_kind: str | None
    start_value: str | None
    base: Decimal | None
    upper: Decimal | None


def validate_start(kind: str | None, value: str | None) -> None:
    """Raise ``ValueError`` unless ``(kind, value)`` is a valid start.

    Mirrors the ``ck_*_gdd_start`` CHECKs in public 0112, so the catalogue
    editor gets a 422 naming the problem instead of an IntegrityError.
    """
    if kind is None:
        if value is not None:
            raise ValueError("gdd_start_value needs a gdd_start_kind")
        return
    if kind not in GDD_START_KINDS:
        raise ValueError(f"gdd_start_kind must be one of {GDD_START_KINDS}")
    if kind == "planting":
        if value is not None:
            raise ValueError("gdd_start_kind 'planting' takes no gdd_start_value")
    elif kind == "date":
        if value is None or not _MMDD_RE.fullmatch(value):
            raise ValueError("gdd_start_kind 'date' needs gdd_start_value as MM-DD")
    elif value is None or not _STAGE_RE.fullmatch(value):
        raise ValueError("gdd_start_kind 'stage' needs gdd_start_value as a stage code")


def resolve_config(
    crop: Any,
    variety: Any | None = None,
    strain: Any | None = None,
) -> HeatUnitConfig:
    """Deepest non-null method and start over crop -> variety -> strain.

    Takes any objects with the catalogue's attribute names (ORM rows in the
    loader, plain namespaces in tests).
    """
    method: str | None = None
    start_kind: str | None = None
    start_value: str | None = None
    for level in (crop, variety, strain):
        if level is None:
            continue
        if getattr(level, "gdd_method", None) is not None:
            method = level.gdd_method
        if getattr(level, "gdd_start_kind", None) is not None:
            start_kind = level.gdd_start_kind
            start_value = getattr(level, "gdd_start_value", None)
    return HeatUnitConfig(
        method=method,
        start_kind=start_kind,
        start_value=start_value,
        base=_dec(getattr(crop, "gdd_base_temp_c", None)),
        upper=_dec(getattr(crop, "gdd_upper_temp_c", None)),
    )


def daily_gdd(
    method: str,
    *,
    tmin: Decimal,
    tmax: Decimal,
    base: Decimal,
    upper: Decimal | None = None,
) -> Decimal:
    """One day's heat units by ``method``. Never negative."""
    if method == "mean":
        value = (tmax + tmin) / _TWO - base
    elif method == "max":
        value = tmax - base
    elif method == "min_max_cutoff":
        lo = _clip(tmin, base, upper)
        hi = _clip(tmax, base, upper)
        value = (hi + lo) / _TWO - base
    else:
        raise ValueError(f"unknown gdd_method {method!r}")
    return max(_ZERO, value)


def most_recent_mmdd(mmdd: str, today: date) -> date | None:
    """The latest ``MM-DD`` on or before ``today``.

    29 February falls back a year at a time to the last leap year, so a
    crop that starts on it still has a start. Returns None for a value that
    is not a calendar day at all (31 April).
    """
    month, day = (int(p) for p in mmdd.split("-"))
    for year in range(today.year, today.year - 8, -1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def resolve_start(
    config: HeatUnitConfig,
    *,
    today: date,
    planting_date: date | None,
    stage_entered: date | None,
    override: date | None,
) -> date | None:
    """The day counting starts, or None when it cannot be known.

    ``stage_entered`` is the date of the latest transition into the stage
    the config names; the caller looks it up only for a ``stage`` start.
    """
    if override is not None:
        return override
    if config.start_kind == "date" and config.start_value:
        return most_recent_mmdd(config.start_value, today)
    if config.start_kind == "planting":
        return planting_date
    if config.start_kind == "stage":
        return stage_entered
    return None


def accumulate(
    config: HeatUnitConfig,
    *,
    start: date,
    today: date,
    days: Iterable[tuple[date, Decimal | None, Decimal | None]],
) -> dict[str, Any]:
    """``{"total", "today", "days_since_start"}`` from daily temperatures.

    ``days`` is ``(date, tmin, tmax)``; rows outside ``[start, today]`` and
    rows missing either temperature are skipped. ``total`` is None when no
    day in the window has both temperatures, ``today`` when today's row has
    not got both. ``days_since_start`` is 0 on the start day.
    """
    assert config.method is not None
    assert config.base is not None
    total = _ZERO
    counted = 0
    today_value: Decimal | None = None
    for day, tmin, tmax in days:
        if day < start or day > today or tmin is None or tmax is None:
            continue
        value = daily_gdd(
            config.method,
            tmin=_dec_req(tmin),
            tmax=_dec_req(tmax),
            base=config.base,
            upper=config.upper,
        )
        total += value
        counted += 1
        if day == today:
            today_value = value
    return {
        "total": total if counted else None,
        "today": today_value,
        "days_since_start": (today - start).days,
    }


async def load_heat_units_snapshot(
    tenant_session: AsyncSession,
    public_session: AsyncSession,
    *,
    block_crop_id: UUID | None,
    farm_id: UUID | None,
    today: date | None = None,
) -> dict[str, Any]:
    """The ``heat_units`` context entry for one block's current crop.

    ``{}`` whenever anything needed is missing (see the module docstring).
    ``tenant_session`` must be bound to the tenant schema.
    """
    if block_crop_id is None or farm_id is None:
        return {}
    today = today or clock.today()
    bc = (
        await tenant_session.execute(select(BlockCrop).where(BlockCrop.id == block_crop_id))
    ).scalar_one_or_none()
    if bc is None:
        return {}
    crop = (
        await public_session.execute(select(Crop).where(Crop.id == bc.crop_id))
    ).scalar_one_or_none()
    if crop is None:
        return {}
    variety = None
    if bc.crop_variety_id is not None:
        variety = (
            await public_session.execute(
                select(CropVariety).where(CropVariety.id == bc.crop_variety_id)
            )
        ).scalar_one_or_none()
    strain = None
    if bc.crop_variety_strain_id is not None:
        strain = (
            await public_session.execute(
                select(CropVarietyStrain).where(CropVarietyStrain.id == bc.crop_variety_strain_id)
            )
        ).scalar_one_or_none()
    config = resolve_config(crop, variety, strain)
    if config.method is None or config.base is None:
        return {}

    stage_entered: date | None = None
    if bc.gdd_start_date is None and config.start_kind == "stage" and config.start_value:
        entered_at = (
            await tenant_session.execute(
                select(GrowthStageLog.transition_date)
                .where(
                    GrowthStageLog.block_crop_id == block_crop_id,
                    GrowthStageLog.stage == config.start_value,
                    GrowthStageLog.deleted_at.is_(None),
                )
                .order_by(GrowthStageLog.transition_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        stage_entered = entered_at.date() if entered_at is not None else None

    start = resolve_start(
        config,
        today=today,
        planting_date=bc.planting_date,
        stage_entered=stage_entered,
        override=bc.gdd_start_date,
    )
    if start is None or start > today:
        return {}
    days = await load_daily_temperatures(tenant_session, farm_id=farm_id, since=start, until=today)
    return accumulate(config, start=start, today=today, days=days)


def _clip(value: Decimal, lo: Decimal, hi: Decimal | None) -> Decimal:
    value = max(value, lo)
    return min(value, hi) if hi is not None else value


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _dec_req(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


__all__ = [
    "GDD_METHODS",
    "GDD_START_KINDS",
    "HeatUnitConfig",
    "accumulate",
    "daily_gdd",
    "load_heat_units_snapshot",
    "most_recent_mmdd",
    "resolve_config",
    "resolve_start",
    "validate_start",
]
