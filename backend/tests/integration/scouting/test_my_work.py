"""W4-B — one feed for work assigned in three different key spaces.

The bug this closes was found in production: a supervisor put a scout on four
board activities, the scout's app showed an empty list, and nothing anywhere
reported a problem. The app could only query ``scouting_visits.assigned_to``;
the board writes ``plan_activities.assigned_membership_id``, and the labour
roster writes ``activity_resources.resource_id``. Same person, three ids.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam import field_enrolment
from app.shared.keycloak import FakeKeycloakClient
from tests.integration.scouting.conftest import ScoutingFixture, build_app

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def fake_keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakClient:
    fake = FakeKeycloakClient()
    monkeypatch.setattr(field_enrolment, "get_keycloak_client", lambda: fake)
    return fake


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _membership_of(session: AsyncSession, user_id) -> UUID:  # type: ignore[no-untyped-def]
    return (
        await session.execute(
            text("SELECT id FROM public.tenant_memberships WHERE user_id = :u LIMIT 1").bindparams(
                bindparam("u", type_=PG_UUID(as_uuid=True))
            ),
            {"u": user_id},
        )
    ).scalar_one()


async def _add_activity(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    block_id: str,
    activity_type: str,
    when: date,
    status: str = "scheduled",
    membership_id: UUID | None = None,
    completed_at: datetime | None = None,
) -> UUID:
    await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    return (
        await session.execute(
            text(
                "INSERT INTO plan_activities "
                "  (farm_id, block_id, activity_type, scheduled_date, status, "
                "   assigned_membership_id, completed_at) "
                "VALUES (CAST(:f AS uuid), CAST(:b AS uuid), :t, :d, :s, :m, :c) "
                "RETURNING id"
            ).bindparams(bindparam("m", type_=PG_UUID(as_uuid=True))),
            {
                "f": farm_id,
                "b": block_id,
                "t": activity_type,
                "d": when,
                "s": status,
                "m": membership_id,
                "c": completed_at,
            },
        )
    ).scalar()


@pytest.mark.asyncio
async def test_board_work_reaches_the_phone(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The production failure, as a test.

    An activity assigned to somebody's *membership* must appear in their feed.
    Before this endpoint it could not: the app asked for visits by user id, and
    a membership is a different id in a different table.
    """
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)
    activity_id = await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="observation",
        when=date.today(),
        membership_id=membership_id,
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        resp = await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    board = [i for i in resp.json() if i["kind"] == "plan_activity"]
    assert [UUID(i["id"]) for i in board] == [activity_id]
    assert board[0]["title"] == "observation"
    assert board[0]["due_at"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_labour_assignment_reaches_the_phone(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The other board path: attached as a *resource*, not named on the row.

    This is how a crew gets scheduled, and it reaches the person through
    ``resources.membership_id`` — a third id again.
    """
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    worker_id = (
        await admin_session.execute(
            text(
                "INSERT INTO resources (kind, name, role, membership_id) "
                "VALUES ('worker', 'Crew Member', 'Scout', :m) RETURNING id"
            ).bindparams(bindparam("m", type_=PG_UUID(as_uuid=True))),
            {"m": membership_id},
        )
    ).scalar()
    await admin_session.execute(
        text(
            "INSERT INTO resource_farms (resource_id, farm_id) VALUES (:r, CAST(:f AS uuid))"
        ).bindparams(bindparam("r", type_=PG_UUID(as_uuid=True))),
        {"r": worker_id, "f": env.farm_id},
    )
    activity_id = await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="spraying",
        when=date.today() + timedelta(days=1),
    )
    await admin_session.execute(
        text(
            "INSERT INTO activity_resources (activity_id, resource_id) VALUES (:a, :r)"
        ).bindparams(
            bindparam("a", type_=PG_UUID(as_uuid=True)),
            bindparam("r", type_=PG_UUID(as_uuid=True)),
        ),
        {"a": activity_id, "r": worker_id},
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        resp = await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    assert activity_id in {UUID(i["id"]) for i in resp.json() if i["kind"] == "plan_activity"}


@pytest.mark.asyncio
async def test_the_feed_is_only_your_own_work(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """Somebody else's assignment must not appear.

    The endpoint carries no capability gate precisely because every row is the
    caller's own — which only holds if the filter is right.
    """
    env = scouting_env
    other_membership = await _membership_of(admin_session, env.agronomist_user_id)
    theirs = await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="pruning",
        when=date.today(),
        membership_id=other_membership,
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        mine = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()
    assert theirs not in {UUID(i["id"]) for i in mine}

    # And the agronomist does see it — the filter excludes, it does not hide.
    async with _client(env.agronomist_context) as client:
        theirs_feed = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()
    assert theirs in {UUID(i["id"]) for i in theirs_feed}


@pytest.mark.asyncio
async def test_completed_work_drops_out_of_the_feed(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """A feed that keeps finished work is a feed nobody trusts."""
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)
    done = await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="observation",
        when=date.today(),
        status="completed",
        membership_id=membership_id,
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        items = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()
    assert done not in {UUID(i["id"]) for i in items}


@pytest.mark.asyncio
async def test_visits_and_board_work_arrive_in_one_ordered_feed(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The whole point: one list, sooner deadline first, whatever set it."""
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)
    await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="spraying",
        when=date.today() + timedelta(days=2),
        membership_id=membership_id,
    )
    # A visit due now — must sort ahead of board work two days out.
    await admin_session.execute(
        text(
            "INSERT INTO scouting_visits "
            "  (farm_id, block_id, origin, status, title, severity, priority, "
            "   assigned_to, due_by) "
            "VALUES (CAST(:f AS uuid), CAST(:b AS uuid), 'ad_hoc', 'assigned', "
            "        'Check the north edge', 'warning', 'high', :u, now())"
        ).bindparams(bindparam("u", type_=PG_UUID(as_uuid=True))),
        {"f": env.farm_id, "b": env.block_id, "u": env.scout_user_id},
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        items = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()

    kinds = [i["kind"] for i in items]
    assert "scouting_visit" in kinds
    assert "plan_activity" in kinds
    assert kinds[0] == "scouting_visit"
    assert [i["due_at"] for i in items] == sorted(i["due_at"] for i in items)


# ---- Finished work -----------------------------------------------------------
#
# `state=closed` exists because the phone's Done tab could not answer for board
# work. It asked the scouting API for completed VISITS, so an activity a scout
# finished left "My work" by being closed and then appeared on no screen at
# all. Measured on production before this was written: the tenant held 0
# scouting visits and 3 completed activities, and Done was empty every time.


@pytest.mark.asyncio
async def test_finished_board_work_is_reachable(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The regression. Both closures come back, and the open feed keeps neither."""
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)
    common = {
        "schema": env.schema,
        "farm_id": env.farm_id,
        "block_id": env.block_id,
        "membership_id": membership_id,
    }
    older = datetime(2026, 8, 27, 21, 44, tzinfo=UTC)
    newer = datetime(2026, 8, 28, 7, 7, tzinfo=UTC)

    did = await _add_activity(
        admin_session,
        activity_type="observation",
        when=date.today(),
        status="completed",
        completed_at=older,
        **common,
    )
    # "Not needed" is a closure the scout performed and a fact the office wants.
    # A Done list holding only "completed" hides half a real day.
    skipped = await _add_activity(
        admin_session,
        activity_type="irrigation",
        when=date.today(),
        status="skipped",
        completed_at=newer,
        **common,
    )
    still_open = await _add_activity(
        admin_session,
        activity_type="observation",
        when=date.today(),
        status="scheduled",
        **common,
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        closed = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}&state=closed")).json()
        open_feed = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()

    closed_ids = [UUID(i["id"]) for i in closed]
    assert did in closed_ids
    assert skipped in closed_ids
    assert still_open not in closed_ids
    # And the two feeds do not overlap: open work is not finished work.
    open_ids = {UUID(i["id"]) for i in open_feed}
    assert still_open in open_ids
    assert did not in open_ids
    assert skipped not in open_ids

    # The closure time travels, because the phone buckets the Done list by the
    # day it was closed. Null here would file every row under "date unknown".
    by_id = {UUID(i["id"]): i for i in closed}
    assert by_id[did]["completed_at"] is not None
    assert by_id[did]["completed_at"].startswith("2026-08-27")
    assert by_id[skipped]["completed_at"].startswith("2026-08-28")
    # Newest first: a proof-of-work list is read from the top.
    assert closed_ids.index(skipped) < closed_ids.index(did)


@pytest.mark.asyncio
async def test_open_feed_still_carries_a_null_closure_time(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """One response shape for one endpoint, whichever state was asked for.

    A field that appears only on the closed feed is one a typed client marks
    optional and then reads as undefined for ever.
    """
    env = scouting_env
    membership_id = await _membership_of(admin_session, env.scout_user_id)
    await _add_activity(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        block_id=env.block_id,
        activity_type="observation",
        when=date.today(),
        membership_id=membership_id,
    )
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        items = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()

    assert items, "the open feed should not be empty"
    assert all("completed_at" in i for i in items)
    assert all(i["completed_at"] is None for i in items)


@pytest.mark.asyncio
async def test_a_cancelled_visit_is_in_neither_feed(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """ "Closed" means "I finished it", not "it is no longer open".

    Work called off by somebody else is not a day's work to show back to the
    person it was called off for.
    """
    env = scouting_env
    await admin_session.execute(text(f"SET search_path TO {env.schema}, public"))
    ids = {}
    # `ck_scouting_visits_outcome_iff_completed` makes the outcome and the
    # status one fact: exactly the completed row may carry an outcome, and it
    # must. Writing a completed visit with a null outcome is rejected.
    for status_value, outcome in (("completed", "resolved"), ("cancelled", None)):
        ids[status_value] = (
            await admin_session.execute(
                text(
                    "INSERT INTO scouting_visits "
                    "  (farm_id, block_id, origin, status, title, severity, priority, "
                    "   assigned_to, outcome, completed_at) "
                    "VALUES (CAST(:f AS uuid), CAST(:b AS uuid), 'ad_hoc', :s, :t, "
                    "        'info', 'medium', :u, :o, now()) "
                    "RETURNING id"
                ).bindparams(bindparam("u", type_=PG_UUID(as_uuid=True))),
                {
                    "f": env.farm_id,
                    "b": env.block_id,
                    "s": status_value,
                    "t": f"a {status_value} visit",
                    "u": env.scout_user_id,
                    "o": outcome,
                },
            )
        ).scalar()
    await admin_session.commit()

    async with _client(env.scout_context) as client:
        closed = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}&state=closed")).json()
        open_feed = (await client.get(f"/api/v1/me/work?farm_id={env.farm_id}")).json()

    closed_ids = {UUID(i["id"]) for i in closed}
    open_ids = {UUID(i["id"]) for i in open_feed}
    assert ids["completed"] in closed_ids
    assert ids["cancelled"] not in closed_ids
    assert ids["cancelled"] not in open_ids
