"""Activity photos on Postgres (investor app v2, build plan 3.3).

Storage is faked; the rest is real: tenant 0110, the init route, attaching on
the complete action in one transaction, the photos on the board and the plan
reads, and the staff-only hide switch (decision D5).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plans import router as plans_router_module
from app.modules.plans.photos import ActivityPhotosService
from app.shared.auth.context import FarmRole, FarmScope
from app.shared.db.session import get_db_session
from app.shared.storage import PresignedDownload, PresignedUpload, StorageObjectMissingError
from tests.integration.farms.conftest import make_context
from tests.integration.plans.test_board_endpoints import _bootstrap_two_blocks, _build_app

pytestmark = [pytest.mark.integration]


class FakeStorage:
    bucket = "uploads"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[int, str]] = {}

    def presign_upload(self, **kwargs: Any) -> PresignedUpload:
        return PresignedUpload(
            url=f"https://s3.test/put/{kwargs['key']}",
            headers={"Content-Type": kwargs["content_type"]},
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    def presign_download(self, **kwargs: Any) -> PresignedDownload:
        return PresignedDownload(
            url=f"https://s3.test/get/{kwargs['key']}",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    def head_object(self, *, key: str) -> dict[str, Any]:
        if key not in self.objects:
            raise StorageObjectMissingError(self.bucket, key)
        size, content_type = self.objects[key]
        return {"ContentLength": size, "ContentType": content_type}


def _app(context: Any, storage: FakeStorage):  # type: ignore[no-untyped-def]
    app = _build_app(context)

    def _photos(session: AsyncSession = Depends(get_db_session)) -> ActivityPhotosService:
        return ActivityPhotosService(session, storage=storage)  # type: ignore[arg-type]

    app.dependency_overrides[plans_router_module._photos] = _photos
    return app


async def _setup(admin_session: AsyncSession, slug: str) -> dict[str, Any]:
    admin_ctx, farm_id, block_id, _ = await _bootstrap_two_blocks(admin_session, slug)
    storage = FakeStorage()
    async with AsyncClient(
        transport=ASGITransport(app=_app(admin_ctx, storage)), base_url="http://test"
    ) as c:
        acts = []
        for _ in range(2):
            r = await c.post(
                f"/api/v1/farms/{farm_id}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "fertilizing",
                    "scheduled_date": date.today().isoformat(),
                },
            )
            assert r.status_code == 201, r.text
            acts.append(r.json()["id"])
    scope = lambda role: (FarmScope(farm_id=UUID(farm_id), role=role),)  # noqa: E731
    return {
        "admin": admin_ctx,
        "scout": make_context(
            user_id=uuid4(), tenant_id=admin_ctx.tenant_id, farm_scopes=scope(FarmRole.SCOUT)
        ),
        "farm_id": farm_id,
        "activity": acts[0],
        "other_activity": acts[1],
        "storage": storage,
    }


async def _upload(c: AsyncClient, storage: FakeStorage, activity_id: str) -> str:
    r = await c.post(
        f"/api/v1/activities/{activity_id}/photos/init",
        json={"content_type": "image/jpeg", "content_length": 2048},
    )
    assert r.status_code == 200, r.text
    key: str = r.json()["s3_key"]
    storage.objects[key] = (2048, "image/jpeg")
    return key


@pytest.mark.asyncio
async def test_a_scout_completes_with_photos_and_staff_see_them(
    admin_session: AsyncSession,
) -> None:
    env = await _setup(admin_session, f"ph-{uuid4().hex[:6]}")
    storage: FakeStorage = env["storage"]
    async with AsyncClient(
        transport=ASGITransport(app=_app(env["scout"], storage)), base_url="http://test"
    ) as c:
        # Only image types are accepted.
        r = await c.post(
            f"/api/v1/activities/{env['activity']}/photos/init",
            json={"content_type": "application/pdf", "content_length": 10},
        )
        assert r.status_code == 422, r.text
        keys = [await _upload(c, storage, env["activity"]) for _ in range(2)]
        assert all(
            k.startswith(
                f"tenants/{env['admin'].tenant_id}/farms/{env['farm_id']}"
                f"/activity-photos/{env['activity']}/"
            )
            for k in keys
        )
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}",
            json={"state": "complete", "attachment_s3_keys": keys},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert len(body["photos"]) == 2
        assert body["photos"][0]["url"].startswith("https://s3.test/get/")
        assert body["photos"][0]["hidden_from_investors"] is False
        assert "s3_key" not in body["photos"][0]

        # A scout cannot hide a photo (plan.manage only): same 404 as missing.
        photo_id = body["photos"][0]["id"]
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}/photos/{photo_id}",
            json={"hidden_from_investors": True},
        )
        assert r.status_code == 404, r.text

    async with AsyncClient(
        transport=ASGITransport(app=_app(env["admin"], storage)), base_url="http://test"
    ) as c:
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}/photos/{photo_id}",
            json={"hidden_from_investors": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["hidden_from_investors"] is True
        r = await c.get(
            f"/api/v1/farms/{env['farm_id']}/board",
            params={"week_start": (date.today() - timedelta(days=1)).isoformat(), "weeks": 1},
        )
        assert r.status_code == 200, r.text
        on_board = next(a for a in r.json()["activities"] if a["id"] == env["activity"])
        assert [p["hidden_from_investors"] for p in on_board["photos"]] == [True, False]
        # A photo id from another activity is not found on this one.
        r = await c.patch(
            f"/api/v1/activities/{env['other_activity']}/photos/{photo_id}",
            json={"hidden_from_investors": False},
        )
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_a_refused_photo_rolls_the_completion_back(admin_session: AsyncSession) -> None:
    env = await _setup(admin_session, f"pr-{uuid4().hex[:6]}")
    storage: FakeStorage = env["storage"]
    async with AsyncClient(
        transport=ASGITransport(app=_app(env["scout"], storage)), base_url="http://test"
    ) as c:
        # A key issued for another activity.
        foreign = await _upload(c, storage, env["other_activity"])
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}",
            json={"state": "complete", "attachment_s3_keys": [foreign]},
        )
        assert r.status_code == 422, r.text
        # A key that was issued but never uploaded.
        r = await c.post(
            f"/api/v1/activities/{env['activity']}/photos/init",
            json={"content_type": "image/png", "content_length": 100},
        )
        never = r.json()["s3_key"]
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}",
            json={"state": "complete", "attachment_s3_keys": [never]},
        )
        assert r.status_code == 422, r.text
        # Photos only travel with the complete action.
        mine = await _upload(c, storage, env["activity"])
        r = await c.patch(
            f"/api/v1/activities/{env['activity']}",
            json={"state": "start", "attachment_s3_keys": [mine]},
        )
        assert r.status_code == 422, r.text

    status_row = (
        await admin_session.execute(
            text(
                f"SELECT a.status, (SELECT count(*) FROM {env['admin'].tenant_schema}"
                ".plan_activity_photos p WHERE p.activity_id = a.id) AS photos "
                f"FROM {env['admin'].tenant_schema}.plan_activities a WHERE a.id = :id"
            ),
            {"id": env["activity"]},
        )
    ).one()
    # Every refused call left the activity as it was, with no photo rows.
    assert status_row.status == "scheduled"
    assert status_row.photos == 0
