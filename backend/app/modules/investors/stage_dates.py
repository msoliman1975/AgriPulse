"""When a block crop's current stage is expected to end.

Pure, so it unit-tests without a database. The rules mirror
``app.modules.farms.phenology_advance``, which moves stages forward:

  * ``calendar_doy``: perennials. The stage ends on ``end_doy`` (MM-DD), the
    next time that date comes round on or after today. This covers a window
    that wraps the new year, such as 12-01 to 01-31.
  * ``days_from_planting``: the planting date plus ``end_day`` days.
  * ``gdd_from_planting`` and ``manual``: no date can be given.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def _mmdd_on_or_after(mmdd: str, today: date) -> date | None:
    try:
        month, day = (int(x) for x in mmdd.split("-"))
    except ValueError:
        return None
    for year in (today.year, today.year + 1, today.year + 4):
        try:
            candidate = date(year, month, day)
        except ValueError:  # 02-29 outside a leap year
            continue
        if candidate >= today:
            return candidate
    return None


def stage_expected_end(
    advance: dict[str, Any] | None, *, planting_date: date | None, today: date
) -> date | None:
    """The expected last day of the stage, or None when it cannot be known."""
    if not isinstance(advance, dict):
        return None
    mode = advance.get("mode")
    if mode == "calendar_doy" and isinstance(advance.get("end_doy"), str):
        return _mmdd_on_or_after(advance["end_doy"], today)
    if mode == "days_from_planting" and planting_date is not None:
        try:
            return planting_date + timedelta(days=int(advance["end_day"]))
        except (KeyError, TypeError, ValueError):
            return None
    return None
