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


def _session(*result_sets: list[Any]) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(rows) for rows in result_sets])
    return session


@pytest.mark.asyncio
class TestGridSignal:
    async def test_marks_only_the_gridded_blocks(self) -> None:
        farm_id = uuid4()
        gridded, plain = uuid4(), uuid4()
        product = uuid4()

        # (1) indices, (2) alerts, (3) grid configs, (4) block roster
        session = _session(
            [],
            [],
            [{"block_id": gridded, "product_id": product}],
            [gridded, plain],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        by_id = {u.id: u for u in out.units}
        assert by_id[gridded].grid_product_id == product
        # An ungridded block must report null, not inherit its neighbour's
        # product — the map would then request cells that do not exist.
        assert by_id[plain].grid_product_id is None

    async def test_a_farm_with_no_zoning_reports_no_products(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        session = _session([], [], [], [b1])

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        # This is what keeps the overlay off: every block null, so the map has
        # nothing to fetch and does not default the grid on.
        assert [u.grid_product_id for u in out.units] == [None]

    async def test_grid_signal_survives_a_block_with_indices_and_alerts(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        product = uuid4()
        now = datetime.now(UTC)

        session = _session(
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.3, "time": now}],
            [{"block_id": b1, "alert_count": 2, "has_critical": True, "has_warning": False}],
            [{"block_id": b1, "product_id": product}],
            [b1],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.grid_product_id == product
        # The pre-existing composition still holds around the new field.
        assert unit.health == "critical"
        assert unit.alert_count == 2
        assert unit.ndvi_current == pytest.approx(0.3)
