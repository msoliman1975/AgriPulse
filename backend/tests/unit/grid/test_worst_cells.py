"""Unit tests for GridService.get_worst_cells ranking.

The ranking is pure logic on top of get_cells_with_values, so we stub
that method and assert the ordering / filtering / limit behaviour without
touching a database.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.grid.schemas import GridCellsResponse, GridCellWithValue
from app.modules.grid.service import GridServiceImpl

PRODUCT = uuid4()
BLOCK = uuid4()


def _cell(mean: str | None, *, row: int, col: int) -> GridCellWithValue:
    return GridCellWithValue(
        cell_id=uuid4(),
        row_idx=row,
        col_idx=col,
        area_m2=Decimal("400.00"),
        centroid_lon=32.0 + col / 1000,
        centroid_lat=30.0 + row / 1000,
        geometry={"type": "Polygon", "coordinates": []},
        mean=None if mean is None else Decimal(mean),
        valid_pixel_pct=None if mean is None else Decimal("100.00"),
        time=None if mean is None else "2026-05-06T10:00:00Z",  # type: ignore[arg-type]
    )


def _service_with_cells(cells: list[GridCellWithValue]) -> GridServiceImpl:
    svc = GridServiceImpl.__new__(GridServiceImpl)  # skip __init__ (no DB)

    async def _fake_get_cells_with_values(**_kwargs: object) -> GridCellsResponse:
        return GridCellsResponse(
            block_id=BLOCK,
            product_id=PRODUCT,
            index_code="ndvi",
            cells=tuple(cells),
            at="2026-05-06T10:00:00Z",  # type: ignore[arg-type]
        )

    svc.get_cells_with_values = _fake_get_cells_with_values  # type: ignore[method-assign]
    return svc


async def _worst(cells: list[GridCellWithValue], limit: int) -> list[Decimal | None]:
    svc = _service_with_cells(cells)
    resp = await svc.get_worst_cells(
        block_id=BLOCK, product_id=PRODUCT, index_code="ndvi", limit=limit, at=None
    )
    return [c.mean for c in resp.cells]


@pytest.mark.asyncio
async def test_orders_ascending_by_mean() -> None:
    cells = [
        _cell("0.80", row=0, col=0),
        _cell("0.20", row=0, col=1),
        _cell("0.50", row=1, col=0),
    ]
    means = await _worst(cells, 10)
    assert means == [Decimal("0.20"), Decimal("0.50"), Decimal("0.80")]


@pytest.mark.asyncio
async def test_excludes_cells_without_observation() -> None:
    cells = [
        _cell("0.40", row=0, col=0),
        _cell(None, row=0, col=1),  # no obs — must be dropped
        _cell("0.10", row=1, col=0),
    ]
    means = await _worst(cells, 10)
    assert means == [Decimal("0.10"), Decimal("0.40")]


@pytest.mark.asyncio
async def test_honours_limit() -> None:
    cells = [_cell(f"0.{i:02d}", row=0, col=i) for i in range(10, 40)]
    means = await _worst(cells, 3)
    assert len(means) == 3
    assert means == [Decimal("0.10"), Decimal("0.11"), Decimal("0.12")]
