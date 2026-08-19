"""The field-flag lifecycle, driven through the HTTP API.

Exercised as the two people who actually use it: a **Scout** with a farm scope
and no tenant role, who raises the flag, and an **Agronomist**, who answers and
closes it. The Scout shape is worth testing explicitly — it is the combination
that used to 403 on every endpoint before #269/#270.

Reuses the scouting fixture because the cast is identical; only the router
mounted differs.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.field_flags.router import router as field_flags_router
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]


def build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(field_flags_router)
    app.add_middleware(StubAuth, context=context)
    return app


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _raise(env: ScoutingFixture, **overrides) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "block_id": env.block_id,
        "note": "Main line cracked near the pump shed, water pooling across the row.",
        "severity": "warning",
        **overrides,
    }
    async with _client(env.scout_context) as client:
        resp = await client.post(f"/api/v1/farms/{env.farm_id}/field-flags", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_scout_raises_a_flag_and_it_is_pinned(scouting_env: ScoutingFixture) -> None:
    flag = await _raise(scouting_env, point={"latitude": 30.61, "longitude": 31.61})

    assert flag["status"] == "open"
    assert flag["severity"] == "warning"
    # The pin lifetime is stored on the row at raise time, not computed on read.
    assert flag["pin_until"] is not None
    assert flag["is_pinned"] is True
    # A position the scout gave is kept as given — never rewritten to the block.
    assert flag["point"]["coordinates"] == pytest.approx([31.61, 30.61])
    assert flag["block_name"]


@pytest.mark.asyncio
async def test_a_flag_without_a_position_is_still_a_flag(scouting_env: ScoutingFixture) -> None:
    # Most flags arrive this way: the scout refused the permission, or the fix
    # never came. Dropping them would lose the finding entirely.
    flag = await _raise(scouting_env)
    assert flag["point"] is None
    assert flag["status"] == "open"


@pytest.mark.asyncio
async def test_closing_records_reason_and_comment_together(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    flag = await _raise(env)

    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            f"/api/v1/field-flags/{flag['id']}:close",
            json={"reason": "no_action_needed", "comment": "Old capped line. Nothing to do."},
        )
    assert resp.status_code == 200, resp.text
    closed = resp.json()

    assert closed["status"] == "closed"
    assert closed["close_reason"] == "no_action_needed"
    assert closed["closed_by"] is not None
    # The comment is the feedback loop, so it has to be ON the thread, not
    # buried in an audit row the scout will never see.
    assert any(c["kind"] == "close" for c in closed["comments"])
    assert "Old capped line" in closed["comments"][-1]["body"]


@pytest.mark.asyncio
async def test_close_without_a_comment_is_refused(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    flag = await _raise(env)
    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            f"/api/v1/field-flags/{flag['id']}:close",
            json={"reason": "actioned", "comment": ""},
        )
    # A flag closed silently reads to the scout as being ignored.
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_scout_cannot_close_their_own_flag(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    flag = await _raise(env)
    async with _client(env.scout_context) as client:
        resp = await client.post(
            f"/api/v1/field-flags/{flag['id']}:close",
            json={"reason": "actioned", "comment": "I fixed it myself."},
        )
    # Closing is a supervisor's act: a scout closing their own flag is
    # answering their own question. 404 rather than 403, matching the rest of
    # this codebase — a caller who cannot act does not learn it exists.
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_the_raiser_may_comment_without_dispatch(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    flag = await _raise(env)
    async with _client(env.scout_context) as client:
        resp = await client.post(
            f"/api/v1/field-flags/{flag['id']}/comments",
            json={"body": "Still leaking this morning."},
        )
    # A thread the reporter cannot answer is not a conversation.
    assert resp.status_code == 200, resp.text
    assert resp.json()["comment_count"] == 1


@pytest.mark.asyncio
async def test_reopening_restarts_the_pin(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    flag = await _raise(env)

    async with _client(env.agronomist_context) as client:
        closed = (
            await client.post(
                f"/api/v1/field-flags/{flag['id']}:close",
                json={"reason": "actioned", "comment": "Crew repaired it."},
            )
        ).json()
    assert closed["status"] == "closed"

    async with _client(env.scout_context) as client:
        resp = await client.post(
            f"/api/v1/field-flags/{flag['id']}:reopen",
            json={"comment": "It is leaking again in the same spot."},
        )
    assert resp.status_code == 200, resp.text
    reopened = resp.json()

    assert reopened["status"] == "open"
    assert reopened["close_reason"] is None
    # The rule that makes "closed pins stay" and "reopen any time" coexist:
    # without a fresh pin_until, a flag reopened after its period ended would
    # be open work with no pin on anybody's map.
    assert reopened["pin_until"] > closed["pin_until"]
    assert reopened["is_pinned"] is True


@pytest.mark.asyncio
async def test_pinned_only_hides_expired_pins_but_the_panel_still_lists_them(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    flag = await _raise(env)

    # Age the pin past its lifetime. Unpinned is NOT closed — the flag is still
    # open work, and the list without `pinned_only` has to keep saying so.
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    # A real UUID object through a typed bindparam, never a CAST over a
    # string — that pattern has taken this platform down three times.
    await admin_session.execute(
        text("UPDATE field_flags SET pin_until = now() - interval '1 day' WHERE id = :id").bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True))
        ),
        {"id": UUID(flag["id"])},
    )
    await admin_session.commit()

    async with _client(env.agronomist_context) as client:
        on_map = (
            await client.get(f"/api/v1/farms/{env.farm_id}/field-flags?pinned_only=true")
        ).json()
        in_panel = (await client.get(f"/api/v1/farms/{env.farm_id}/field-flags")).json()

    assert all(f["id"] != flag["id"] for f in on_map)
    listed = next(f for f in in_panel if f["id"] == flag["id"])
    assert listed["status"] == "open"
    assert listed["is_pinned"] is False
