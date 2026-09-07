"""Blocks summary — the grid signal the map's default overlay reads.

The map turns its sub-block grid on when any block in the farm is zoned. It
learns that from this endpoint: without `grid_product_id` here it would have
to ask every block for its imagery subscriptions before drawing a single
cell, which is the fan-out that exhausted the connection pool on that page.

The SQL itself was run against a live tenant schema; these cover the
composition, which is where a block can silently get someone else's product.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.farms.blocks_summary_router import get_blocks_summary


class _Result:
    """Stands in for a SQLAlchemy Result across the two access shapes the
    endpoint uses: `.mappings().all()` and `.scalars().all()`."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        # The farm-override read uses `.first()`. Empty here means the farm
        # has no override, which is what every test in this file wants.
        return self._rows[0] if self._rows else None


def _session(
    *,
    badge: list[Any] | None = None,
    grid: list[Any] | None = None,
    roster: list[Any] | None = None,
    indices: list[Any] | None = None,
    unbounded: list[Any] | None = None,
) -> AsyncMock:
    """Feed `execute` its results, named rather than positional.

    Only the four this file cares about are named; the eight health-evidence
    queries it never varies are stubbed empty. The full call order lives in
    `test_blocks_summary_health_evidence._session`, which is the one place
    that knows it — this file used to carry its own copy as a bare list of
    lists, and it broke silently every time a query was added.

    `unbounded` is the second, unbounded index sweep, issued only for
    blocks the recent window found nothing for. It defaults to not being
    supplied, so an unexpected fallback fails loudly.
    """
    sets: list[list[Any]] = [
        badge or [],
        [],  # alert evidence      ┐
        [],  # recommendations     │ the evidence loader's
        [],  # trace counts        │ six statements
        [],  # verdicts            │
        [],  # grid cell counts    │
        [],  # crop paths          ┘
        [],  # per-crop health definitions
        [],  # this farm's health override
        grid or [],
        roster or [],
        indices or [],
    ]
    if unbounded is not None:
        sets.append(unbounded)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(rows) for rows in sets])
    return session


@pytest.mark.asyncio
class TestGridSignal:
    async def test_marks_only_the_gridded_blocks(self) -> None:
        farm_id = uuid4()
        gridded, plain = uuid4(), uuid4()
        product = uuid4()

        # No indices at all, so both blocks are stale and the unbounded
        # fallback sweep runs too — hence the fifth set.
        session = _session(
            grid=[{"block_id": gridded, "product_id": product}],
            roster=[gridded, plain],
            unbounded=[],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        by_id = {u.id: u for u in out.units}
        assert by_id[gridded].grid_product_id == product
        # An ungridded block must report null, not inherit its neighbour's
        # product — the map would then request cells that do not exist.
        assert by_id[plain].grid_product_id is None

    async def test_a_farm_with_no_zoning_reports_no_products(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        session = _session(roster=[b1], unbounded=[])

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        # This is what keeps the overlay off: every block null, so the map has
        # nothing to fetch and does not default the grid on.
        assert [u.grid_product_id for u in out.units] == [None]

    async def test_grid_signal_survives_a_block_with_indices_and_alerts(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        product = uuid4()
        now = datetime.now(UTC)

        # b1 has a recent reading, so no unbounded fallback sweep: `unbounded`
        # is left unset and an extra call would exhaust side_effect and fail.
        session = _session(
            badge=[
                {
                    "block_id": b1,
                    "alert_count": 2,
                    "has_critical": True,
                    "has_warning": False,
                    "alert_action_type": "irrigate",
                }
            ],
            grid=[{"block_id": b1, "product_id": product}],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.3, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.grid_product_id == product
        # The pre-existing composition still holds around the new field.
        assert unit.health == "critical"
        assert unit.alert_count == 2
        assert unit.alert_action_type == "irrigate"
        assert unit.ndvi_current == pytest.approx(0.3)
