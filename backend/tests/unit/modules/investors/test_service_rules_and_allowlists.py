"""Service rules that no default role exercises, and the investor-app allowlists.

R8 (a sold holding's boundary needs `holding.redraw_sold`) is held by every
role that can edit holdings today, so no integration test reaches the refusal.
A company can still remove the capability on the Roles & permissions page, so
the rule is tested here against a stub repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.investors.errors import HoldingOwnedError
from app.modules.investors.schemas import InvestorAppHoldingResponse, InvestorAppMeResponse
from app.modules.investors.service import InvestorsService

_FARM = uuid4()
_HOLDING = uuid4()
_SQUARE = {
    "type": "Polygon",
    "coordinates": [[[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.001], [31.0, 30.0]]],
}


def _row() -> dict[str, Any]:
    return {
        "id": _HOLDING,
        "farm_id": _FARM,
        "status": "available",
        "archived_at": None,
        "area_m2": Decimal("100"),
        "share_pct": Decimal("1"),
        "current_ownership_id": uuid4(),
        "current_investor_id": uuid4(),
        "current_investor_code": "INV-0001",
        "current_investor_name": "Nour",
        "current_investor_name_ar": None,
        "current_since": datetime(2026, 1, 1, tzinfo=UTC).date(),
    }


def _service() -> InvestorsService:
    svc = InvestorsService(
        tenant_session=AsyncMock(), tenant_schema="tenant_x", audit_service=AsyncMock()
    )
    repo = AsyncMock()
    repo.get_holding.return_value = _row()
    repo.holding_has_open_ownership.return_value = True
    repo.geometry_problem.return_value = None
    svc._repo = repo
    return svc


@pytest.mark.asyncio
async def test_r8_sold_holding_boundary_needs_the_capability() -> None:
    svc = _service()
    with pytest.raises(HoldingOwnedError):
        await svc.update_holding(
            farm_id=_FARM,
            holding_id=_HOLDING,
            changes={"boundary": _SQUARE},
            can_redraw_sold=False,
            actor_user_id=None,
        )
    svc._repo.update_holding.assert_not_called()


@pytest.mark.asyncio
async def test_r8_renaming_a_sold_holding_needs_nothing_extra() -> None:
    svc = _service()
    await svc.update_holding(
        farm_id=_FARM,
        holding_id=_HOLDING,
        changes={"name": "New name"},
        can_redraw_sold=False,
        actor_user_id=None,
    )
    svc._repo.update_holding.assert_awaited_once()


@pytest.mark.asyncio
async def test_r8_with_the_capability_the_boundary_changes() -> None:
    svc = _service()
    await svc.update_holding(
        farm_id=_FARM,
        holding_id=_HOLDING,
        changes={"boundary": _SQUARE},
        can_redraw_sold=True,
        actor_user_id=None,
    )
    kwargs = svc._repo.update_holding.await_args.kwargs
    assert kwargs["boundary_ewkt"].startswith("SRID=4326;POLYGON")


def test_investor_app_holding_fields_are_pinned() -> None:
    """Adding a field to what an investor sees must be a deliberate change."""
    assert set(InvestorAppHoldingResponse.model_fields) == {
        "holding_id",
        "code",
        "name",
        "name_ar",
        "farm_name",
        "farm_name_ar",
        "block_code",
        "block_name",
        "block_name_ar",
        "area_m2",
        "tree_count",
        "crop_name_en",
        "crop_name_ar",
        "variety_name_en",
        "variety_name_ar",
        "planting_date",
        "start_date",
        "end_date",
        "period",
        "boundary",
        "block_boundary",
    }


def test_investor_app_me_fields_are_pinned() -> None:
    assert set(InvestorAppMeResponse.model_fields) == {
        "code",
        "full_name",
        "full_name_ar",
        "preferred_language",
        "company_name",
    }
