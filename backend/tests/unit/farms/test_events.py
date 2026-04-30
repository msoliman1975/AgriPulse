"""Unit tests for farms event payload shapes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.modules.farms.events import (
    BlockBoundaryChangedV1,
    BlockCreatedV1,
    FarmCreatedV1,
    FarmMemberAssignedV1,
)


def test_farm_created_event_serializes() -> None:
    ev = FarmCreatedV1(
        farm_id=uuid4(),
        code="FARM-1",
        name="Test",
        area_m2=Decimal("1234.56"),
        actor_user_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    payload = ev.model_dump(mode="json")
    assert payload["code"] == "FARM-1"
    assert ev.event_name == "farms.farm_created.v1"


def test_block_created_event_carries_aoi_hash() -> None:
    ev = BlockCreatedV1(
        block_id=uuid4(),
        farm_id=uuid4(),
        code="B-1",
        area_m2=Decimal("100"),
        aoi_hash="deadbeef",
    )
    assert ev.aoi_hash == "deadbeef"
    assert ev.event_name == "farms.block_created.v1"


def test_block_boundary_changed_carries_prev_and_new() -> None:
    ev = BlockBoundaryChangedV1(
        block_id=uuid4(),
        farm_id=uuid4(),
        prev_aoi_hash="old",
        new_aoi_hash="new",
    )
    assert ev.prev_aoi_hash == "old"
    assert ev.new_aoi_hash == "new"


def test_member_assigned_event() -> None:
    ev = FarmMemberAssignedV1(
        farm_scope_id=uuid4(),
        membership_id=uuid4(),
        farm_id=uuid4(),
        role="FarmManager",
    )
    assert ev.role == "FarmManager"
    assert ev.event_name == "farms.farm_member_assigned.v1"


def test_event_is_frozen() -> None:
    ev = FarmCreatedV1(
        farm_id=uuid4(),
        code="X",
        name="X",
        area_m2=Decimal("0"),
        created_at=datetime.now(UTC),
    )
    import pytest

    with pytest.raises((AttributeError, TypeError, ValueError)):
        ev.code = "Y"  # type: ignore[misc]
