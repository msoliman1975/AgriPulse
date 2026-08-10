"""Handover history for a block's responsible member.

The column names one person and remembers nothing. Once dispatch started
defaulting to it, "who was responsible in March" became a real question, and
the audit trail cannot answer it — `farms.block_updated` records changed field
*names* and no values.

These tests pin the parts that are easy to get subtly wrong: that a no-op save
writes nothing, that unassigning is recorded rather than skipped, and that the
predecessor recorded is the value that was actually there.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.farms.repository import FarmsRepository
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}
_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


async def _seed(admin_session: Any) -> tuple[FarmsRepository, dict[str, Any]]:
    if not _SHARED:
        slug = f"brl-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

        farm_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO farms (
                        code, name, country_code, boundary, boundary_utm, centroid, area_m2
                    ) VALUES (
                        'BRL', 'Responsible farm', 'EG',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000
                    ) RETURNING id
                    """
                ),
                {"poly": _POLY},
            )
        ).scalar_one()
        block_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO blocks (
                        farm_id, code, boundary, boundary_utm, centroid,
                        area_m2, aoi_hash
                    ) VALUES (
                        :farm_id, 'R-01',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                        100000, 'hash-r01'
                    ) RETURNING id
                    """
                ),
                {"farm_id": farm_id, "poly": _POLY},
            )
        ).scalar_one()
        await admin_session.commit()
        _SHARED.update(schema=str(tenant.schema_name), farm_id=farm_id, block_id=block_id)

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return FarmsRepository(tenant_session=admin_session, public_session=admin_session), _SHARED


@pytest.fixture(autouse=True)
async def _reset_search_path(admin_session: Any):
    yield
    # `SET search_path` is connection state and rides the pooled connection
    # into the next test if it is not reset.
    await admin_session.execute(text("RESET search_path"))


@pytest.mark.asyncio
async def test_first_assignment_records_no_predecessor(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    who = uuid4()
    res = await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=who, note="initial owner", actor_user_id=None
    )
    assert res is not None
    assert res["changed"] is True
    assert res["previous_membership_id"] is None

    log = await repo.list_block_responsible_log(block_id=seeded["block_id"])
    assert log[0]["new_membership_id"] == who
    assert log[0]["previous_membership_id"] is None
    assert log[0]["note"] == "initial owner"


@pytest.mark.asyncio
async def test_a_handover_records_the_person_it_came_from(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    first, second = uuid4(), uuid4()
    await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=first, note=None, actor_user_id=None
    )
    await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=second, note="on leave", actor_user_id=None
    )
    log = await repo.list_block_responsible_log(block_id=seeded["block_id"])
    # Newest first.
    assert log[0]["previous_membership_id"] == first
    assert log[0]["new_membership_id"] == second
    assert log[0]["note"] == "on leave"


@pytest.mark.asyncio
async def test_saving_the_same_person_writes_nothing(admin_session: Any) -> None:
    """Re-saving is not a handover. Logging it would bury the real ones."""
    repo, seeded = await _seed(admin_session)
    who = uuid4()
    await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=who, note=None, actor_user_id=None
    )
    before = len(await repo.list_block_responsible_log(block_id=seeded["block_id"]))

    res = await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=who, note="again", actor_user_id=None
    )
    assert res is not None
    assert res["changed"] is False
    after = await repo.list_block_responsible_log(block_id=seeded["block_id"])
    assert len(after) == before


@pytest.mark.asyncio
async def test_unassigning_is_recorded(admin_session: Any) -> None:
    """An ownerless block is what makes dispatch fall back to an arbitrary
    member, so losing an owner is exactly the event worth keeping."""
    repo, seeded = await _seed(admin_session)
    who = uuid4()
    await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=who, note=None, actor_user_id=None
    )
    res = await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=None, note="left the org", actor_user_id=None
    )
    assert res is not None
    assert res["changed"] is True
    log = await repo.list_block_responsible_log(block_id=seeded["block_id"])
    assert log[0]["previous_membership_id"] == who
    assert log[0]["new_membership_id"] is None


@pytest.mark.asyncio
async def test_the_column_actually_moves(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    who = uuid4()
    await repo.set_block_responsible(
        block_id=seeded["block_id"], new_membership_id=who, note=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    current = (
        await admin_session.execute(
            text("SELECT agronomist_membership_id FROM blocks WHERE id = :b"),
            {"b": seeded["block_id"]},
        )
    ).scalar_one()
    assert current == who


@pytest.mark.asyncio
async def test_history_is_newest_first_and_limited(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    people = [uuid4() for _ in range(4)]
    for m in people:
        await repo.set_block_responsible(
            block_id=seeded["block_id"], new_membership_id=m, note=None, actor_user_id=None
        )
    log = await repo.list_block_responsible_log(block_id=seeded["block_id"], limit=2)
    assert len(log) == 2
    assert log[0]["new_membership_id"] == people[-1]


@pytest.mark.asyncio
async def test_a_missing_block_is_none_not_a_crash(admin_session: Any) -> None:
    repo, _ = await _seed(admin_session)
    assert (
        await repo.set_block_responsible(
            block_id=uuid4(), new_membership_id=uuid4(), note=None, actor_user_id=None
        )
        is None
    )


@pytest.mark.asyncio
async def test_history_of_a_block_with_no_handovers_is_empty(admin_session: Any) -> None:
    repo, _ = await _seed(admin_session)
    assert await repo.list_block_responsible_log(block_id=uuid4()) == ()


def _unused(_: UUID) -> None:  # pragma: no cover - keeps the UUID import honest
    return None
