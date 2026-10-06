"""Pure parts of the investors service: the polygon check and the derived status."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.modules.investors.errors import HoldingGeometryError
from app.modules.investors.service import _shape_holding, polygon_to_ewkt

_RING = [[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.001], [31.0, 30.0]]


def test_polygon_becomes_ewkt_in_4326() -> None:
    ewkt = polygon_to_ewkt({"type": "Polygon", "coordinates": [_RING]})
    assert ewkt.startswith("SRID=4326;POLYGON((31.0 30.0, 31.001 30.0")
    assert ewkt.endswith("31.0 30.0))")


@pytest.mark.parametrize(
    ("geom", "fragment"),
    [
        ({"type": "MultiPolygon", "coordinates": [[_RING]]}, "GeoJSON Polygon"),
        ({"type": "Polygon", "coordinates": []}, "no coordinates"),
        ({"type": "Polygon", "coordinates": [_RING, _RING]}, "holes"),
        ({"type": "Polygon", "coordinates": [_RING[:3]]}, "3 corners"),
        ({"type": "Polygon", "coordinates": [_RING[:-1] + [[31.0, 30.0005]]]}, "closed"),
        ({"type": "Polygon", "coordinates": [[[200, 30], *_RING[1:-1], [200, 30]]]}, "outside"),
    ],
)
def test_bad_polygons_are_refused(geom: dict[str, Any], fragment: str) -> None:
    with pytest.raises(HoldingGeometryError) as exc:
        polygon_to_ewkt(geom)
    assert fragment in exc.value.detail


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": "available",
        "archived_at": None,
        "share_pct": Decimal("10.00"),
        "current_ownership_id": None,
        "current_investor_id": None,
        "current_investor_code": None,
        "current_investor_name": None,
        "current_investor_name_ar": None,
        "current_since": None,
    }
    row.update(overrides)
    return row


def test_a_holding_with_a_current_owner_reads_as_sold() -> None:
    owner = uuid4()
    shaped = _shape_holding(
        _row(
            current_ownership_id=uuid4(),
            current_investor_id=owner,
            current_investor_code="INV-0001",
            current_investor_name="Nour",
            current_since=date(2026, 1, 1),
        )
    )
    assert shaped["status"] == "sold"
    assert shaped["current_owner"]["investor_id"] == owner
    assert shaped["current_owner"]["since"] == date(2026, 1, 1)


def test_archived_wins_over_everything() -> None:
    shaped = _shape_holding(
        _row(archived_at=datetime(2026, 1, 1, tzinfo=UTC), current_ownership_id=uuid4())
    )
    assert shaped["status"] == "archived"


def test_a_holding_with_no_owner_keeps_its_stored_status() -> None:
    assert _shape_holding(_row(status="draft"))["status"] == "draft"
    assert _shape_holding(_row())["current_owner"] is None


def test_missing_block_area_gives_zero_share_not_none() -> None:
    assert _shape_holding(_row(share_pct=None))["share_pct"] == Decimal("0")
