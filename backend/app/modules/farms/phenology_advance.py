"""Pure resolver: which phenology stage a block is in on a given date.

Used by the ``phenology.advance_growth_stages`` Beat task to move a block
through its (taxonomy-resolved) stages automatically. Kept pure (no DB,
no I/O) so it unit-tests fast.

Advance modes (validated upstream against ``Crop.is_perennial`` in
``app.modules.farms.phenology``):

  * ``calendar_doy`` — perennials. ``MM-DD`` windows, wrap-around allowed
    (e.g. 12-01 → 01-31). Evaluated against today's month/day.
  * ``days_from_planting`` — annuals. ``[start_day, end_day)`` elapsed days
    since ``planting_date``.
  * ``gdd_from_planting`` — annuals; needs accumulated GDD (farm weather).
    NOT resolved here in V1 — these stages are skipped (no seeded crop uses
    GDD; see proposal §6 follow-up). Pass ``gdd_cumulative`` to enable.
  * ``manual`` — never auto-advanced.

When more than one stage window matches, the highest ``order`` wins.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _parse_mmdd(value: str) -> tuple[int, int]:
    month, day = value.split("-")
    return int(month), int(day)


def _doy_in_window(today: date, start_mmdd: str, end_mmdd: str) -> bool:
    t = (today.month, today.day)
    start = _parse_mmdd(start_mmdd)
    end = _parse_mmdd(end_mmdd)
    if start <= end:
        return start <= t <= end
    # Wrap-around window (e.g. Dec → Jan): match either tail.
    return t >= start or t <= end


def stage_for_date(
    stages: list[dict[str, Any]],
    *,
    is_perennial: bool,
    planting_date: date | None,
    today: date,
    gdd_cumulative: float | None = None,
) -> str | None:
    """Return the code of the stage whose window contains ``today``.

    Returns ``None`` when no stage matches (so the caller leaves the block's
    stage unchanged). Manual stages and — in V1 — GDD stages without a
    supplied ``gdd_cumulative`` never match.
    """
    matches: list[dict[str, Any]] = []
    for stage in stages:
        advance = stage.get("advance") or {}
        mode = advance.get("mode")
        if mode == "calendar_doy" and is_perennial:
            if _doy_in_window(today, advance["start_doy"], advance["end_doy"]):
                matches.append(stage)
        elif mode == "days_from_planting" and not is_perennial and planting_date is not None:
            elapsed = (today - planting_date).days
            if advance["start_day"] <= elapsed < advance["end_day"]:
                matches.append(stage)
        elif (
            mode == "gdd_from_planting"
            and not is_perennial
            and gdd_cumulative is not None
            and advance["start_gdd"] <= gdd_cumulative < advance["end_gdd"]
        ):
            matches.append(stage)
        # manual / unsupported / missing-anchor -> never matches
    if not matches:
        return None
    winner = max(matches, key=lambda s: s.get("order", 0))
    return str(winner["code"])


__all__ = ["stage_for_date"]
