"""Dispatch writes real board activities — including the failure cases.

The write path is where this feature can quietly do the wrong thing:
* assign nobody and say it assigned someone,
* take the whole batch down because one item was bad,
* or link an alert to an activity it does not own.

Each of those gets a test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.action_center.service import ActionCenterServiceImpl
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}
_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


async def _seed(admin_session: Any) -> dict[str, Any]:
    """A farm with two blocks: one has a responsible member, one does not."""
    if not _SHARED:
        slug = f"acd-{uuid4().hex[:8]}"
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
                        'ACD', 'Dispatch farm', 'EG',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000
                    ) RETURNING id
                    """
                ),
                {"poly": _POLY},
            )
        ).scalar_one()

        owner = uuid4()
        blocks: dict[str, UUID] = {}
        for code, responsible in (("D-01", owner), ("D-02", None)):
            blocks[code] = (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO blocks (
                            farm_id, code, boundary, boundary_utm, centroid,
                            area_m2, aoi_hash, agronomist_membership_id
                        ) VALUES (
                            :farm_id, :code,
                            ST_GeomFromText(:poly, 4326),
                            ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                            ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                            100000, :hash, :responsible
                        ) RETURNING id
                        """
                    ),
                    {
                        "farm_id": farm_id,
                        "code": code,
                        "poly": _POLY,
                        "hash": f"h-{code}",
                        "responsible": responsible,
                    },
                )
            ).scalar_one()

        async def _rec(block: UUID, action: str) -> UUID:
            return (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO recommendations (
                            block_id, farm_id, tree_id, tree_code, tree_version,
                            action_type, severity, parameters, confidence,
                            tree_path, evaluation_snapshot, text_en, state
                        ) VALUES (
                            :block, :farm, gen_random_uuid(), 'acd_v1', 1,
                            :action, 'warning', '{}'::jsonb, 0.7,
                            '[]'::jsonb, '{}'::jsonb, 'Do the thing', 'open'
                        ) RETURNING id
                        """
                    ),
                    {"block": block, "farm": farm_id, "action": action},
                )
            ).scalar_one()

        rec_owned = await _rec(blocks["D-01"], "spray")
        rec_unowned = await _rec(blocks["D-02"], "scout")

        alert_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO alerts (
                        block_id, rule_code, action_type, severity, status, diagnosis_en
                    ) VALUES (
                        :block, 'tree:acd_alert_v1:leaf', 'irrigate', 'critical',
                        'open', 'Dry'
                    ) RETURNING id
                    """
                ),
                {"block": blocks["D-01"]},
            )
        ).scalar_one()

        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            farm_id=farm_id,
            blocks=blocks,
            owner=owner,
            rec_owned=rec_owned,
            rec_unowned=rec_unowned,
            alert_id=alert_id,
        )

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return _SHARED


async def _use(admin_session: Any) -> None:
    """Re-pin the tenant search_path.

    `SET search_path` is connection state, and a commit can hand the session a
    different pooled connection — after which every unqualified table name in
    this module resolves against `public` and 500s. Any test that commits
    mid-way has to re-pin before it queries again.
    """
    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))


def _service(session: Any) -> ActionCenterServiceImpl:
    return ActionCenterServiceImpl(tenant_session=session)


@pytest.mark.asyncio
async def test_dispatch_defaults_to_the_blocks_responsible_member(admin_session: Any) -> None:
    """The whole point of comment C: nobody types a name for a block that
    already has an owner."""
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=None,
        scheduled_date=date(2026, 8, 10),
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    assert result.dispatched == 1
    assert result.failed == 0
    entry = result.results[0]
    assert entry.assigned_membership_id == seeded["owner"]
    assert entry.assignee_defaulted is True
    assert entry.activity_id is not None


@pytest.mark.asyncio
async def test_the_activity_actually_carries_the_assignee(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=None,
        scheduled_date=date(2026, 8, 11),
        notes="check the east rows",
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    await admin_session.commit()
    await _use(admin_session)
    row = (
        (
            await admin_session.execute(
                text(
                    """
                SELECT assigned_membership_id, activity_type, scheduled_date,
                       notes, recommendation_id
                FROM plan_activities WHERE id = :id
                """
                ),
                {"id": result.results[0].activity_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["assigned_membership_id"] == seeded["owner"]
    # spray -> spraying, via the action->activity map
    assert row["activity_type"] == "spraying"
    assert row["scheduled_date"] == date(2026, 8, 11)
    assert row["notes"] == "check the east rows"
    assert row["recommendation_id"] == seeded["rec_owned"]


@pytest.mark.asyncio
async def test_an_explicit_assignee_overrides_the_block_owner(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    chosen = uuid4()
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=chosen,
        scheduled_date=None,
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    assert result.results[0].assigned_membership_id == chosen
    # Not a default — the caller said so explicitly, and the UI uses this flag
    # to decide whether to explain where the name came from.
    assert result.results[0].assignee_defaulted is False


@pytest.mark.asyncio
async def test_a_block_with_no_owner_still_dispatches_and_admits_it(
    admin_session: Any,
) -> None:
    """A silent arbitrary assignment would be worse than none — the result
    flags that the name was not chosen by anyone."""
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_unowned"]],
        assigned_membership_id=None,
        scheduled_date=None,
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    assert result.dispatched == 1
    assert result.results[0].assignee_defaulted is True


@pytest.mark.asyncio
async def test_dispatching_an_alert_links_it_to_its_activity(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["alert_id"]],
        assigned_membership_id=None,
        scheduled_date=None,
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    await admin_session.commit()
    await _use(admin_session)
    assert result.results[0].kind == "alert"
    linked = (
        await admin_session.execute(
            text("SELECT prescription_activity_id FROM alerts WHERE id = :id"),
            {"id": seeded["alert_id"]},
        )
    ).scalar_one()
    assert linked == result.results[0].activity_id
    # irrigate -> irrigation
    activity_type = (
        await admin_session.execute(
            text("SELECT activity_type FROM plan_activities WHERE id = :id"),
            {"id": linked},
        )
    ).scalar_one()
    assert activity_type == "irrigation"


@pytest.mark.asyncio
async def test_one_bad_item_does_not_take_the_batch_down(admin_session: Any) -> None:
    """Per-item SAVEPOINT. Without it the aborted transaction would fail every
    remaining item in the batch — the cross-tenant-loop lesson, applied here."""
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[uuid4(), seeded["rec_owned"], uuid4()],
        assigned_membership_id=None,
        scheduled_date=None,
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    assert result.dispatched == 1
    assert result.failed == 2
    assert [r.error for r in result.results] == ["not_found", None, "not_found"]


@pytest.mark.asyncio
async def test_an_item_from_another_farm_is_not_dispatchable(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=uuid4(),
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=None,
        scheduled_date=None,
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    assert result.dispatched == 0
    assert result.results[0].error == "not_found"


@pytest.mark.asyncio
async def test_a_dispatched_item_reads_back_as_dispatched(admin_session: Any) -> None:
    """End-to-end: the write moves the row between tabs on the next read.

    The recommendations table still says `open` — there is no native state for
    "sent to someone" — so this only works if the assignee folds into the
    unified status.
    """
    seeded = await _seed(admin_session)
    service = _service(admin_session)
    await service.dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=None,
        scheduled_date=date(2026, 8, 12),
        notes=None,
        actor_user_id=None,
        tenant_schema=seeded["schema"],
    )
    await admin_session.commit()
    await _use(admin_session)

    listing = await service.list_items(farm_id=seeded["farm_id"], group_by="none")
    item = next(i for g in listing.groups for i in g.items if i.id == seeded["rec_owned"])
    assert item.status == "dispatched"
    assert item.native_status == "open"
    assert item.assigned_membership_id == seeded["owner"]
    assert item.scheduled_date == date(2026, 8, 12)


@pytest.mark.asyncio
async def test_status_counts_ignore_the_status_filter(admin_session: Any) -> None:
    """A tab must never advertise a count the active filters have excluded —
    but it must still count rows the *tab* excludes."""
    seeded = await _seed(admin_session)
    listing = await _service(admin_session).list_items(
        farm_id=seeded["farm_id"], status="needs_action", group_by="none"
    )
    total_in_counts = sum(v for k, v in listing.status_counts.items() if k != "all")
    assert listing.status_counts["all"] == total_in_counts
    # The filtered list is a subset of what the counts describe.
    assert listing.total <= listing.status_counts["all"]


@pytest.mark.asyncio
async def test_a_far_future_raised_from_filters_everything_out(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    listing = await _service(admin_session).list_items(
        farm_id=seeded["farm_id"],
        raised_from=datetime(2030, 1, 1, tzinfo=UTC),
        group_by="none",
    )
    assert listing.total == 0
    assert listing.status_counts["all"] == 0


@pytest.mark.asyncio
async def test_dispatching_to_scout_opens_a_visit_not_a_board_activity(
    admin_session: Any,
) -> None:
    """The link that makes the phone the destination.

    Action Center originally dispatched only to the board, while the mobile app
    reads `scouting_visits` — so a triaged item could never reach a handset.
    """
    seeded = await _seed(admin_session)
    result = await _service(admin_session).dispatch(
        farm_id=seeded["farm_id"],
        item_ids=[seeded["rec_owned"]],
        assigned_membership_id=None,
        scheduled_date=date(2026, 8, 10),
        notes="Walk the north edge.",
        actor_user_id=None,
        tenant_schema=seeded["schema"],
        target="scout",
    )
    assert result.dispatched == 1, result.results
    entry = result.results[0]
    assert entry.visit_id is not None
    assert entry.activity_id is None  # a visit, not board work

    row = (
        (
            await admin_session.execute(
                text(
                    "SELECT origin, status, recommendation_id, assigned_to, due_by, "
                    "reason_snapshot->>'note' AS note "
                    "FROM scouting_visits WHERE id = :v"
                ),
                {"v": entry.visit_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["origin"] == "recommendation"
    assert row["recommendation_id"] == seeded["rec_owned"]
    # The supervisor's words survive: `instruction` is CHECK-limited to ad_hoc,
    # so a non-ad_hoc visit carries them in reason_snapshot instead.
    # This fixture's "owner" is a bare uuid4 with no membership behind it, so
    # no Keycloak subject resolves. The visit must still land — queued, so any
    # scout on the farm can claim it — and the result must NOT claim it was
    # assigned to someone it was not.
    assert row["status"] == "queued"
    assert row["assigned_to"] is None
    assert entry.assigned_membership_id is None
    assert entry.assignee_defaulted is False
    # End of the working day, not midday: "today" must not arrive overdue.
    assert row["due_by"].hour == 18


@pytest.mark.asyncio
async def test_dispatching_the_same_item_to_a_scout_twice_does_not_duplicate_it(
    admin_session: Any,
) -> None:
    """The routing rules may already have opened a visit for this item.

    Triaging it by hand afterwards must not put the same walk on the list
    twice; the partial UNIQUE catches it and it reports as already dispatched
    rather than as an error.
    """
    seeded = await _seed(admin_session)
    svc = _service(admin_session)
    kwargs: dict[str, Any] = {
        "farm_id": seeded["farm_id"],
        "item_ids": [seeded["alert_id"]],
        "assigned_membership_id": None,
        "scheduled_date": None,
        "notes": None,
        "actor_user_id": None,
        "tenant_schema": seeded["schema"],
        "target": "scout",
    }
    first = await svc.dispatch(**kwargs)
    assert first.results[0].visit_id is not None

    second = await svc.dispatch(**kwargs)
    entry = second.results[0]
    assert entry.already_dispatched is True
    assert entry.error is None
    assert entry.visit_id is None

    count = (
        await admin_session.execute(
            text("SELECT count(*) FROM scouting_visits WHERE alert_id = :a"),
            {"a": seeded["alert_id"]},
        )
    ).scalar_one()
    assert count == 1
