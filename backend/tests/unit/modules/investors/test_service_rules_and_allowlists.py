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
from app.modules.investors.schemas import (
    InvestorAppHoldingResponse,
    InvestorAppMeResponse,
    InvestorAppVersionResponse,
)
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
        # Build plan v2, PR 1: the crop's public picture, nothing tenant-specific.
        "crop_image_url",
        "crop_icon_url",
        # Build plan v2, PR 2: the stage code, the dated stage list and the
        # expected harvest start.
        "stage_code",
        "stages",
        "expected_harvest_on",
        "stage_name_en",
        "stage_name_ar",
        "stage_started_on",
        "stage_expected_end",
        "current_season",
        "start_date",
        "end_date",
        "period",
        # D3 (build plan v2, PR 2b): their own ownership facts.
        "acquired_by",
        "contract_ref",
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
        # Build plan v2, PR 2: their own status, type and contact details.
        "status",
        "investor_type",
        "email",
        "phone",
    }


def test_investor_app_me_leaves_out_staff_only_fields() -> None:
    staff_only = {
        "notes_internal",
        "national_id_type",
        "national_id_last4",
        "relationship_manager_id",
        "user_id",
        "id",
    }
    assert staff_only.isdisjoint(InvestorAppMeResponse.model_fields)


def test_investor_app_stage_fields_are_pinned() -> None:
    from app.modules.investors.schemas import InvestorAppStage

    # Names and dates only: never the advance rule, Kc or thresholds.
    assert set(InvestorAppStage.model_fields) == {
        "code",
        "name_en",
        "name_ar",
        "expected_start",
        "expected_end",
    }


def test_investor_app_version_fields_are_pinned() -> None:
    assert set(InvestorAppVersionResponse.model_fields) == {
        "min_version",
        "latest_version",
        "download_url",
    }


def test_investor_app_holding_turns_image_keys_into_urls() -> None:
    """The crop image keys are read for the URLs and never reach the investor."""
    from app.modules.investors.service import _with_stage_end

    crop_key = "platform/crop-images/crops/" + str(_FARM) + "/" + str(_HOLDING) + "/original.png"
    row = {
        "crop_image_key": crop_key,
        "variety_image_key": None,
        "stage_advance": None,
        "stage_name_en": None,
        "stage_name_ar": None,
        "stage_list": [
            {
                "code": "harvest",
                "name_en": "Harvest",
                "name_ar": "الحصاد",
                "order": 1,
                "kc": "0.9",
                "advance": {"mode": "calendar_doy", "start_doy": "09-10", "end_doy": "10-14"},
            }
        ],
    }
    out = _with_stage_end(row)
    assert "stage_list" not in out
    assert out["stages"][0]["code"] == "harvest"
    assert set(out["stages"][0]) == {"code", "name_en", "name_ar", "expected_start", "expected_end"}
    assert out["expected_harvest_on"] == out["stages"][0]["expected_start"]
    assert "crop_image_key" not in out
    assert "variety_image_key" not in out
    assert out["crop_image_url"].endswith(f"/crops/{_FARM}/{_HOLDING}/256.webp")
    assert out["crop_icon_url"].endswith(f"/crops/{_FARM}/{_HOLDING}/64.webp")
    assert set(out) <= set(InvestorAppHoldingResponse.model_fields)


# ---- Build plan v2, PR 4: activities and site photo (D4, D5) ---------------


def test_investor_app_activity_fields_are_pinned() -> None:
    from app.modules.investors.schemas import InvestorAppActivity, InvestorAppActivityPhoto

    # D4: title and type, date, status, photos. Never product, dosage or notes.
    assert set(InvestorAppActivity.model_fields) == {
        "id",
        "activity_type",
        "title",
        "title_ar",
        "scheduled_date",
        "status",
        "completed_at",
        "photos",
    }
    assert set(InvestorAppActivityPhoto.model_fields) == {"thumb_url", "url", "taken_at"}


def test_investor_app_site_photo_fields_are_pinned() -> None:
    from app.modules.investors.schemas import InvestorAppSitePhoto, InvestorAppSitePhotoResponse

    assert set(InvestorAppSitePhotoResponse.model_fields) == {"holding_id", "photo"}
    assert set(InvestorAppSitePhoto.model_fields) == {"url", "taken_at"}


def test_season_is_the_active_plans_year_else_this_year() -> None:
    from datetime import date

    from app.modules.investors.service import season_window

    today = date(2026, 11, 16)
    assert season_window("2026", today) == (date(2026, 1, 1), date(2026, 12, 31))
    assert season_window("2025/26", today) == (date(2025, 1, 1), date(2025, 12, 31))
    assert season_window(None, today) == (date(2026, 1, 1), date(2026, 12, 31))
    assert season_window("winter", today) == (date(2026, 1, 1), date(2026, 12, 31))


def test_activities_window_is_clipped_to_the_ownership() -> None:
    from datetime import date

    from app.modules.investors.service import ownership_window

    today = date(2026, 11, 16)
    current = {"current_season": "2026", "start_date": date(2026, 3, 1), "end_date": None}
    assert ownership_window(current, today) == (date(2026, 3, 1), date(2026, 12, 31))
    past = {"current_season": "2026", "start_date": date(2025, 1, 1), "end_date": date(2026, 6, 30)}
    assert ownership_window(past, today) == (date(2026, 1, 1), date(2026, 6, 30))
    # Ended before this season began: nothing to show.
    gone = {"current_season": "2026", "start_date": date(2024, 1, 1), "end_date": date(2025, 5, 1)}
    assert ownership_window(gone, today) is None
