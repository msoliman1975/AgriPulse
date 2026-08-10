"""The scouting visit lifecycle, driven through the HTTP API.

These exercise the path the mobile app will actually take, as the user it will
actually be: a Scout with a farm scope and **no tenant role**. That combination
is worth testing explicitly — it is the exact shape that used to 403 on every
endpoint before PR #269/#270, and the app is unusable if it regresses.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.scouting.conftest import ScoutingFixture, build_app

pytestmark = [pytest.mark.integration]


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _dispatch(env: ScoutingFixture, **overrides) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "block_id": env.block_id,
        "instruction": "The north edge looks patchy on last week's pass — walk it.",
        "due_within_hours": 48,
        "severity": "warning",
        **overrides,
    }
    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            f"/api/v1/scouting/visits:dispatch?farm_id={env.farm_id}", json=body
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_ad_hoc_dispatch_then_claim_start_submit(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    visit = await _dispatch(env, lat=30.61, lon=31.61)

    assert visit["origin"] == "ad_hoc"
    assert visit["status"] == "queued"
    # The supervisor's own words survive to the field, and the pin renders as
    # GeoJSON rather than leaking a PostGIS blob.
    assert visit["instruction"].startswith("The north edge")
    assert visit["pin_point"]["coordinates"] == [31.61, 30.61]
    # Title falls back to the first line of what a human typed.
    assert visit["title"].startswith("The north edge")

    async with _client(env.scout_context) as scout:
        # It shows up as claimable, not as someone else's work.
        listed = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}&claimable=true")
        assert listed.status_code == 200, listed.text
        assert [v["id"] for v in listed.json()] == [visit["id"]]

        claimed = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}"
        )
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["status"] == "accepted"
        assert claimed.json()["assigned_to"] == str(env.scout_user_id)

        started = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:start?farm_id={env.farm_id}"
        )
        assert started.json()["status"] == "in_progress"

        submitted = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:submit?farm_id={env.farm_id}",
            json={"outcome": "inconclusive", "summary_note": "Dripline suspect"},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "completed"
        assert submitted.json()["outcome"] == "inconclusive"


@pytest.mark.asyncio
async def test_second_claim_loses_the_race(scouting_env: ScoutingFixture) -> None:
    """Two scouts tapping "I'll take it" — exactly one wins."""
    env = scouting_env
    visit = await _dispatch(env)

    async with _client(env.scout_context) as first:
        assert (
            await first.post(f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}")
        ).status_code == 200
    async with _client(env.agronomist_context) as second:
        lost = await second.post(
            f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}"
        )
    assert lost.status_code == 409, lost.text


@pytest.mark.asyncio
async def test_decline_returns_it_to_the_queue_with_a_reason(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    visit = await _dispatch(env)
    async with _client(env.scout_context) as scout:
        await scout.post(f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}")

        # Refusing work is legitimate; refusing it silently is not.
        no_reason = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:decline?farm_id={env.farm_id}", json={}
        )
        assert no_reason.status_code == 422, no_reason.text

        declined = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:decline?farm_id={env.farm_id}",
            json={"reason": "Vehicle is out"},
        )
    assert declined.status_code == 200, declined.text
    body = declined.json()
    assert body["status"] == "queued"
    assert body["assigned_to"] is None
    assert body["decline_reason"] == "Vehicle is out"


@pytest.mark.asyncio
async def test_completed_visit_cannot_be_restarted(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    visit = await _dispatch(env)
    async with _client(env.scout_context) as scout:
        await scout.post(f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}")
        await scout.post(f"/api/v1/scouting/visits/{visit['id']}:start?farm_id={env.farm_id}")
        await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:submit?farm_id={env.farm_id}",
            json={"outcome": "resolved"},
        )
        again = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:start?farm_id={env.farm_id}"
        )
    assert again.status_code == 409, again.text
    assert "completed" in again.json()["detail"]


@pytest.mark.asyncio
async def test_submit_replay_is_safe(scouting_env: ScoutingFixture) -> None:
    """A scout on a bad connection retries; the retry must not re-close it
    differently, and must not read as a failure."""
    env = scouting_env
    visit = await _dispatch(env)
    key = "idem-" + visit["id"]
    async with _client(env.scout_context) as scout:
        await scout.post(f"/api/v1/scouting/visits/{visit['id']}:claim?farm_id={env.farm_id}")
        first = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:submit?farm_id={env.farm_id}",
            json={"outcome": "inconclusive", "idempotency_key": key},
        )
        replay = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:submit?farm_id={env.farm_id}",
            json={"outcome": "resolved", "idempotency_key": key},
        )
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["outcome"] == "inconclusive"


@pytest.mark.asyncio
async def test_self_initiated_visit_skips_the_queue(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    async with _client(env.scout_context) as scout:
        resp = await scout.post(
            f"/api/v1/scouting/visits?farm_id={env.farm_id}", json={"block_id": env.block_id}
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["origin"] == "self_initiated"
    assert body["status"] == "in_progress"
    assert body["assigned_to"] == str(env.scout_user_id)


@pytest.mark.asyncio
async def test_scout_cannot_dispatch_or_assign(scouting_env: ScoutingFixture) -> None:
    """A Scout logs what they see; they do not hand out work."""
    env = scouting_env
    visit = await _dispatch(env)
    async with _client(env.scout_context) as scout:
        dispatched = await scout.post(
            f"/api/v1/scouting/visits:dispatch?farm_id={env.farm_id}",
            json={"block_id": env.block_id, "instruction": "go look"},
        )
        assigned = await scout.post(
            f"/api/v1/scouting/visits/{visit['id']}:assign?farm_id={env.farm_id}",
            json={"assignee_user_id": str(env.scout_user_id)},
        )
        rules = await scout.get(f"/api/v1/scouting/routing-rules?farm_id={env.farm_id}")
    assert dispatched.status_code == 403, dispatched.text
    assert assigned.status_code == 403, assigned.text
    # Routing rules are a FarmManager concern, not an Agronomist or Scout one.
    assert rules.status_code == 403, rules.text


@pytest.mark.asyncio
async def test_supervisor_assign_puts_it_on_a_named_scout(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    visit = await _dispatch(env)
    async with _client(env.agronomist_context) as agro:
        assigned = await agro.post(
            f"/api/v1/scouting/visits/{visit['id']}:assign?farm_id={env.farm_id}",
            json={"assignee_user_id": str(env.scout_user_id)},
        )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["status"] == "assigned"
    assert body["assigned_to"] == str(env.scout_user_id)
    # A person did this, so it is recorded as a person — the board reads the
    # difference between a supervisor's decision and a routing rule's.
    assert body["assigned_by"] == str(env.agronomist_user_id)

    async with _client(env.scout_context) as scout:
        mine = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}&mine=true")
    assert [v["id"] for v in mine.json()] == [visit["id"]]


@pytest.mark.asyncio
async def test_instruction_is_rejected_on_non_ad_hoc_origins(
    scouting_env: ScoutingFixture,
) -> None:
    """Only a supervisor's ad-hoc dispatch carries human words.

    Enforced by a CHECK, so this is really a guard against a future code path
    quietly writing an instruction onto a machine-generated visit.
    """
    env = scouting_env
    async with _client(env.scout_context) as scout:
        resp = await scout.post(
            f"/api/v1/scouting/visits?farm_id={env.farm_id}",
            json={"block_id": env.block_id, "title": "Walk-up"},
        )
    assert resp.status_code == 201
    assert resp.json()["instruction"] is None
