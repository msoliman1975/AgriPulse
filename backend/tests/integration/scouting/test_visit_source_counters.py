"""What a scout is told about the finding behind their visit (0079).

A visit is written once. The finding it came from goes on being re-evaluated
every morning, and two things about it change afterwards that change what a
scout should do on arrival: how many grid cells it now covers, and how long it
has been true. Both are read live off the source row rather than snapshotted
into `reason_snapshot`, because a snapshot of a moving number is a stale number.

Worth an integration test for two reasons.

First, the join. `_VISIT_COLUMNS` is shared by three queries — list, get, and
the idempotency replay — and adding LEFT JOINs to `recommendations` and
`alerts` made every bare column name in it ambiguous, `id` most of all. A
column list that resolves for one of the three and not the others is exactly
the shape that passes a happy-path test and 500s in the field.

Second, the default. Most visits have no decision-engine source at all —
routine, ad-hoc, self-initiated — so every joined column comes back NULL. Those
must render as "one occurrence, no group", not as nulls the app has to guess at.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.scouting.conftest import ScoutingFixture, build_app

pytestmark = [pytest.mark.integration]


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _dispatch_ad_hoc(env: ScoutingFixture) -> dict:  # type: ignore[no-untyped-def]
    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            f"/api/v1/scouting/visits:dispatch?farm_id={env.farm_id}",
            json={
                "block_id": env.block_id,
                "instruction": "Walk the north edge.",
                "severity": "warning",
            },
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_a_visit_with_no_engine_source_reports_sane_defaults(
    scouting_env: ScoutingFixture,
) -> None:
    """An ad-hoc visit has nothing to join to, and must say so plainly."""
    env = scouting_env
    visit = await _dispatch_ad_hoc(env)

    assert visit["source"] == {
        "is_group": False,
        "member_count": 0,
        "previous_member_count": 0,
        "trend": "unknown",
        "occurrence_count": 1,
        "day_streak": 1,
        "first_seen_at": None,
        "last_seen_at": None,
    }

    # Same shape through the list and the single-get, which are separate
    # statements built from the same column fragment.
    async with _client(env.scout_context) as scout:
        listed = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}&claimable=true")
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["source"]["occurrence_count"] == 1

        one = await scout.get(f"/api/v1/scouting/visits/{visit['id']}?farm_id={env.farm_id}")
        assert one.status_code == 200, one.text
        assert one.json()["source"]["is_group"] is False


@pytest.mark.asyncio
async def test_a_visit_from_a_group_carries_its_extent_and_its_age(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """One visit, nine zones, six mornings running.

    The counters are written on the recommendation by the evaluator, not on the
    visit — so this seeds the source row directly and asserts the join carries
    it through to the shape the phone reads.
    """
    env = scouting_env
    await admin_session.execute(text(f'SET search_path TO "{env.schema}", public'))

    rec_id = uuid4()
    await admin_session.execute(
        text(
            """
            INSERT INTO recommendations (
                id, block_id, farm_id, tree_id, tree_code, tree_version,
                action_type, severity, parameters, confidence, tree_path,
                evaluation_snapshot, text_en, state,
                group_key, is_group, member_count, previous_member_count,
                occurrence_count, day_streak, first_seen_at, last_seen_at
            ) VALUES (
                :id, :block_id, :farm_id, gen_random_uuid(), 'scout_tree_v1', 1,
                'scout', 'warning', '{}'::jsonb, 0.9, '[]'::jsonb,
                '{}'::jsonb, 'Scout these zones', 'open',
                'scout_tree_v1:leaf:scout:warning', TRUE, 9, 4, 6, 6,
                now() - interval '6 days', now()
            )
            """
        ),
        {"id": rec_id, "block_id": env.block_id, "farm_id": env.farm_id},
    )

    visit = await _dispatch_ad_hoc(env)
    await admin_session.execute(
        text(
            # `instruction` is CHECK-constrained to ad_hoc visits only, so
            # re-homing this one to the engine has to drop the human sentence
            # along with the origin — same as a real engine-raised visit,
            # which never had one.
            "UPDATE scouting_visits SET recommendation_id = :r, "
            "origin = 'recommendation', instruction = NULL WHERE id = :v"
        ),
        {"r": rec_id, "v": visit["id"]},
    )
    await admin_session.commit()

    async with _client(env.scout_context) as scout:
        resp = await scout.get(f"/api/v1/scouting/visits/{visit['id']}?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    source = resp.json()["source"]

    assert source["is_group"] is True
    # One visit standing for nine cells is the whole point — nine visits is
    # what this replaced.
    assert source["member_count"] == 9
    assert source["day_streak"] == 6
    assert source["occurrence_count"] == 6
    assert source["first_seen_at"] is not None
    # Nine zones today against four yesterday. A scout walking a spreading
    # outbreak needs that before they arrive; a bare count cannot tell them.
    assert source["previous_member_count"] == 4
    assert source["trend"] == "spreading"


@pytest.mark.asyncio
async def test_the_alert_side_of_the_join_works_too(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """A visit points at a recommendation OR an alert, and the two are
    COALESCEd. Testing only one side leaves the other free to be wrong."""
    env = scouting_env
    await admin_session.execute(text(f'SET search_path TO "{env.schema}", public'))

    alert_id = uuid4()
    await admin_session.execute(
        text(
            """
            INSERT INTO alerts (
                id, block_id, rule_code, severity, action_type, status,
                diagnosis_en, group_key, is_group, member_count,
                previous_member_count,
                occurrence_count, day_streak, first_seen_at, last_seen_at
            ) VALUES (
                :id, :block_id, 'tree:heat_v1:leaf_hot', 'critical', 'irrigate',
                'open', 'Soil moisture below wilting point',
                'heat_v1:leaf_hot:irrigate:critical', TRUE, 4, 12, 3, 3,
                now() - interval '3 days', now()
            )
            """
        ),
        {"id": alert_id, "block_id": env.block_id},
    )

    visit = await _dispatch_ad_hoc(env)
    await admin_session.execute(
        text(
            "UPDATE scouting_visits SET alert_id = :a, origin = 'alert', "
            "instruction = NULL WHERE id = :v"
        ),
        {"a": alert_id, "v": visit["id"]},
    )
    await admin_session.commit()

    async with _client(env.scout_context) as scout:
        listed = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}")
    assert listed.status_code == 200, listed.text
    row = next(v for v in listed.json() if v["id"] == visit["id"])
    assert row["source"]["member_count"] == 4
    assert row["source"]["day_streak"] == 3
    # Four cells today against twelve yesterday: this one is receding, and the
    # alert side of the COALESCE has to say so as clearly as the rec side.
    assert row["source"]["trend"] == "receding"
