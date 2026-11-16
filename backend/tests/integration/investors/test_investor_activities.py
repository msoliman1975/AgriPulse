"""Investor activities and site photo on Postgres (build plan 3.4, D4, D5).

The investor sees the season's activities on their holding's block, inside
their ownership: no skipped ones, no product or notes, no photo staff hid,
and nothing from someone else's holding.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.investors import service as investors_service
from app.modules.plans.router import router as plans_router
from app.shared.auth.context import TenantRole
from app.shared.storage import PresignedDownload
from tests.integration.farms.conftest import make_context
from tests.integration.investors.test_investments_area import (
    _LON0,
    _client,
    _login,
    _sold_holding,
)
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]


class _Links:
    def presign_download(self, **kwargs: Any) -> PresignedDownload:
        return PresignedDownload(
            url=f"https://s3.test/get/{kwargs['key']}",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )


def _plans_client(context: Any) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(plans_router)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _activity(c: AsyncClient, env: ScoutingFixture, on: date, kind: str) -> str:
    r = await c.post(
        f"/api/v1/farms/{env.farm_id}/activities",
        json={
            "block_id": env.block_id,
            "activity_type": kind,
            "scheduled_date": on.isoformat(),
            "product_name": "Secret mix",
            "notes": "staff only",
        },
    )
    assert r.status_code == 201, r.text
    activity_id: str = r.json()["id"]
    return activity_id


async def _photo(
    session: AsyncSession, schema: str, activity_id: str, key: str, hidden: bool, at: datetime
) -> None:
    await session.execute(
        text(
            f"INSERT INTO {schema}.plan_activity_photos "
            "(activity_id, s3_key, taken_at, hidden_from_investors) "
            "VALUES (:a, :k, :t, :h)"
        ),
        {"a": activity_id, "k": key, "t": at, "h": hidden},
    )


@pytest.mark.asyncio
async def test_investor_sees_the_seasons_activities_and_visible_photos(
    scouting_env: ScoutingFixture, admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = scouting_env
    monkeypatch.setattr(investors_service, "get_storage_client", lambda: _Links())
    mine, investor = await _sold_holding(env, _LON0)
    today = date.today()

    async with _plans_client(env.admin_context) as c:
        done = await _activity(c, env, today, "fertilizing")
        r = await c.patch(f"/api/v1/activities/{done}", json={"state": "complete"})
        assert r.status_code == 200, r.text
        upcoming = await _activity(c, env, today, "irrigation")
        skipped = await _activity(c, env, today, "spraying")
        r = await c.patch(f"/api/v1/activities/{skipped}", json={"state": "skip"})
        assert r.status_code == 200, r.text
        # Before the ownership started (it started today): not theirs to see.
        before = await _activity(c, env, today - timedelta(days=1), "pruning")
        # Next calendar year: outside this season.
        await _activity(c, env, date(today.year + 1, 1, 15), "pruning")

    now = datetime.now(UTC)
    await _photo(admin_session, env.schema, done, "k/visible.jpg", False, now)
    await _photo(admin_session, env.schema, done, "k/hidden.jpg", True, now + timedelta(minutes=5))
    await _photo(admin_session, env.schema, before, "k/before.jpg", False, now - timedelta(days=1))
    await admin_session.commit()

    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        r = await c.get(f"/api/v1/investor/holdings/{mine['id']}/activities")
        assert r.status_code == 200, r.text
        acts = {a["id"]: a for a in r.json()}
        site = await c.get(f"/api/v1/investor/holdings/{mine['id']}/site-photo")

    assert set(acts) == {done, upcoming}
    assert acts[done]["status"] == "completed"
    assert acts[upcoming]["status"] == "upcoming"
    # D4: names, dates, status and photos only.
    assert set(acts[done]) == {
        "id",
        "activity_type",
        "title",
        "title_ar",
        "scheduled_date",
        "status",
        "completed_at",
        "photos",
    }
    # D5: the hidden photo never reaches the investor.
    assert [p["url"] for p in acts[done]["photos"]] == ["https://s3.test/get/k/visible.jpg"]
    assert acts[upcoming]["photos"] == []

    # The newest visible photo; the newer hidden one is skipped.
    assert site.status_code == 200, site.text
    assert site.json()["photo"]["url"] == "https://s3.test/get/k/visible.jpg"


@pytest.mark.asyncio
async def test_another_investors_holding_gives_nothing_away(
    scouting_env: ScoutingFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = scouting_env
    monkeypatch.setattr(investors_service, "get_storage_client", lambda: _Links())
    _mine, investor = await _sold_holding(env, _LON0)
    theirs, _ = await _sold_holding(env, _LON0 + 0.001)
    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        acts = await c.get(f"/api/v1/investor/holdings/{theirs['id']}/activities")
        site = await c.get(f"/api/v1/investor/holdings/{theirs['id']}/site-photo")
    assert acts.status_code == 404, acts.text
    assert site.status_code == 404, site.text

    # A staff token has no investor reads.
    async with _client(env.admin_context) as c:
        r = await c.get(f"/api/v1/investor/holdings/{theirs['id']}/activities")
    assert r.status_code == 403, r.text
