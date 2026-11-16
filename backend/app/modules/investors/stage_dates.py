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


# ---- The season's stage list (investor app v2, build plan 3.2) -------------

#: Stage codes that mark the start of picking, most specific first. The
#: catalogue has no "harvest" flag, so the seeded codes decide: Medjool has
#: ``harvest``, mango and potato ``maturation``, the generic date palm
#: calendar ``rutab`` then ``tamar``.
HARVEST_STAGE_CODES: tuple[str, ...] = ("harvest", "maturation", "rutab", "tamar")


def _mmdd_on_or_before(mmdd: str, today: date) -> date | None:
    try:
        month, day = (int(x) for x in mmdd.split("-"))
    except ValueError:
        return None
    for year in (today.year, today.year - 1, today.year - 4):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def _ordered(stages: Any) -> list[dict[str, Any]]:
    if not isinstance(stages, list):
        return []
    valid = [s for s in stages if isinstance(s, dict) and isinstance(s.get("code"), str)]

    def _order(stage: dict[str, Any]) -> int:
        order = stage.get("order")
        return order if isinstance(order, int) else 0

    return sorted(valid, key=_order)


def season_stages(stages: Any, *, planting_date: date | None, today: date) -> list[dict[str, Any]]:
    """The crop's stages in order, each with the dates expected this season.

    ``[{code, name_en, name_ar, expected_start, expected_end}]``.

    * ``calendar_doy``: the season starts on the first stage's ``start_doy``,
      the latest one on or before today; each later stage starts on the next
      occurrence of its own ``start_doy`` and ends on the next ``end_doy``, so
      a window over the new year (12-01 to 02-15) lands in the right years.
    * ``days_from_planting``: planting date plus ``start_day`` / ``end_day``.
    * ``gdd_from_planting``, ``manual`` or anything unreadable: null dates.
      The app then gives those stages equal widths.
    """
    ordered = _ordered(stages)
    out: list[dict[str, Any]] = []
    cursor: date | None = None
    for stage in ordered:
        raw_advance = stage.get("advance")
        advance: dict[str, Any] = raw_advance if isinstance(raw_advance, dict) else {}
        start: date | None = None
        end: date | None = None
        mode = advance.get("mode")
        if mode == "calendar_doy":
            start_doy, end_doy = advance.get("start_doy"), advance.get("end_doy")
            if isinstance(start_doy, str) and isinstance(end_doy, str):
                # The first calendar stage anchors the season on today; each
                # later one follows the stage before it.
                start = (
                    _mmdd_on_or_before(start_doy, today)
                    if cursor is None
                    else _mmdd_on_or_after(start_doy, cursor)
                )
                end = _mmdd_on_or_after(end_doy, start) if start else None
                cursor = start or cursor
        elif mode == "days_from_planting" and planting_date is not None:
            try:
                start = planting_date + timedelta(days=int(advance["start_day"]))
                end = planting_date + timedelta(days=int(advance["end_day"]))
            except (KeyError, TypeError, ValueError):
                start = end = None
        out.append(
            {
                "code": stage["code"],
                "name_en": stage.get("name_en"),
                "name_ar": stage.get("name_ar"),
                "expected_start": start,
                "expected_end": end,
            }
        )
    return out


def expected_harvest_on(season: list[dict[str, Any]]) -> date | None:
    """Expected first day of the harvest (or maturation) stage, or None."""
    by_code = {s["code"]: s for s in season}
    for code in HARVEST_STAGE_CODES:
        stage = by_code.get(code)
        if stage is not None:
            start: date | None = stage["expected_start"]
            return start
    return None
