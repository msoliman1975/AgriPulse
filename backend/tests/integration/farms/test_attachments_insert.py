"""Farm and block attachments reach the database.

These tests exist because the only other attachment suite,
`tests/unit/farms/test_attachments_service.py`, replaces the repository with a
mock. The INSERT statement therefore never ran anywhere, and it could not run:
it wrapped the geometry bind in ``CASE WHEN :geo IS NULL THEN NULL ELSE
ST_GeomFromEWKT(:geo) END``. A parameter whose only other use is ``IS NULL``
gives Postgres nothing to infer a type from, so the statement failed to
prepare with ``could not determine data type of parameter``, whatever value was
passed. Every farm and block attachment upload returned 500 at the finalize
step, on every deployment the feature has had.

The cases below cover both owner kinds and both geometry states, because the
failure was in preparing the statement and so did not depend on the value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import TenantRole
from app.shared.storage.client import PresignedDownload, PresignedUpload

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]

JPEG = "image/jpeg"
SIZE = 193
POINT = {"type": "Point", "coordinates": [31.2005, 30.0005]}


class _FakeStorage:
    """Stands in for R2. The bytes are not what these tests are about."""

    bucket = "test-bucket"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def presign_upload(
        self, *, key: str, content_type: str, content_length: int
    ) -> PresignedUpload:
        return PresignedUpload(
            url=f"https://storage.test/{key}?signed",
            headers={"Content-Type": content_type, "Content-Length": str(content_length)},
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

    def presign_download(self, *, key: str) -> PresignedDownload:
        return PresignedDownload(
            url=f"https://storage.test/{key}?download",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

    def head_object(self, *, key: str) -> dict[str, Any]:
        return {"ContentLength": SIZE, "ContentType": JPEG}

    def delete_object(self, *, key: str) -> None:
        self.deleted.append(key)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> _FakeStorage:
    fake = _FakeStorage()
    monkeypatch.setattr(
        "app.modules.farms.service.get_storage_client",
        lambda: fake,
    )
    return fake


async def _tenant_app(admin_session: AsyncSession, slug: str):
    from app.modules.tenancy.service import get_tenant_service

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return build_app(context)


async def _make_farm(c: AsyncClient, code: str = "FARM-A") -> str:
    resp = await c.post(
        "/api/v1/farms",
        json={"code": code, "name": "Attachment Host", "boundary": _square(31.2, 30.0)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_block(c: AsyncClient, farm_id: str) -> str:
    resp = await c.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={
            "code": "B-1",
            "name": "Block One",
            "boundary": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [31.2, 30.0],
                        [31.201, 30.0],
                        [31.201, 30.001],
                        [31.2, 30.001],
                        [31.2, 30.0],
                    ]
                ],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(
    c: AsyncClient,
    *,
    init_path: str,
    finalize_path: str,
    filename: str,
    geo_point: dict[str, Any] | None,
) -> dict[str, Any]:
    """init, then finalize. Returns the finalize body."""
    resp = await c.post(
        init_path,
        json={
            "kind": "photo",
            "original_filename": filename,
            "content_type": JPEG,
            "size_bytes": SIZE,
        },
    )
    assert resp.status_code == 200, resp.text
    init = resp.json()

    resp = await c.post(
        finalize_path,
        json={
            "attachment_id": init["attachment_id"],
            "s3_key": init["s3_key"],
            "kind": "photo",
            "original_filename": filename,
            "content_type": JPEG,
            "size_bytes": SIZE,
            "caption": "field photo",
            "geo_point": geo_point,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("geo_point", [None, POINT], ids=["no_geo_point", "with_geo_point"])
async def test_farm_attachment_insert_reaches_the_database(
    admin_session: AsyncSession,
    storage: _FakeStorage,
    geo_point: dict[str, Any] | None,
) -> None:
    app = await _tenant_app(admin_session, f"att-farm-{'geo' if geo_point else 'nogeo'}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _make_farm(c)
        body = await _upload(
            c,
            init_path=f"/api/v1/farms/{farm_id}/attachments:init",
            finalize_path=f"/api/v1/farms/{farm_id}/attachments",
            filename="north-block.jpg",
            geo_point=geo_point,
        )
        assert body["owner_kind"] == "farm"
        assert body["size_bytes"] == SIZE
        assert body["download_url"].startswith("https://storage.test/")

        # Read it back from its own query, not from the create response.
        resp = await c.get(f"/api/v1/farms/{farm_id}/attachments")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == body["id"]
        assert row["original_filename"] == "north-block.jpg"
        assert row["caption"] == "field photo"
        if geo_point is None:
            assert row["geo_point"] is None
        else:
            assert row["geo_point"]["type"] == "Point"
            lon, lat = row["geo_point"]["coordinates"]
            assert lon == pytest.approx(31.2005)
            assert lat == pytest.approx(30.0005)


@pytest.mark.asyncio
@pytest.mark.parametrize("geo_point", [None, POINT], ids=["no_geo_point", "with_geo_point"])
async def test_block_attachment_insert_reaches_the_database(
    admin_session: AsyncSession,
    storage: _FakeStorage,
    geo_point: dict[str, Any] | None,
) -> None:
    app = await _tenant_app(admin_session, f"att-block-{'geo' if geo_point else 'nogeo'}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _make_farm(c, code="FARM-B")
        block_id = await _make_block(c, farm_id)
        body = await _upload(
            c,
            init_path=f"/api/v1/blocks/{block_id}/attachments:init",
            finalize_path=f"/api/v1/blocks/{block_id}/attachments",
            filename="row-12.jpg",
            geo_point=geo_point,
        )
        assert body["owner_kind"] == "block"
        assert body["owner_id"] == block_id

        resp = await c.get(f"/api/v1/blocks/{block_id}/attachments")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        if geo_point is None:
            assert rows[0]["geo_point"] is None
        else:
            assert rows[0]["geo_point"]["type"] == "Point"


@pytest.mark.asyncio
async def test_farm_attachment_delete_removes_row_and_object(
    admin_session: AsyncSession, storage: _FakeStorage
) -> None:
    app = await _tenant_app(admin_session, "att-farm-delete")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _make_farm(c, code="FARM-D")
        body = await _upload(
            c,
            init_path=f"/api/v1/farms/{farm_id}/attachments:init",
            finalize_path=f"/api/v1/farms/{farm_id}/attachments",
            filename="deed.jpg",
            geo_point=None,
        )

        resp = await c.delete(f"/api/v1/farms/attachments/{body['id']}")
        assert resp.status_code in (200, 204), resp.text
        assert body["s3_key"] in storage.deleted

        resp = await c.get(f"/api/v1/farms/{farm_id}/attachments")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
