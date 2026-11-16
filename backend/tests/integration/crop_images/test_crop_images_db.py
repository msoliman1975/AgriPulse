"""Crop images on Postgres (investor app v2, build plan 3.1).

Storage is faked (no S3 in CI); the rest is real: the 0114 columns and their
CHECK, the admin upload routes, the renditions task body, the public image
route, and the URLs on the crop catalogue, block crop reads and the board.

A fresh crop and variety are created for this file, so no other test sees
an image appear on a seeded crop.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crop_images import router as crop_images_router
from app.modules.crop_images import service as crop_images_service
from app.modules.crop_images.renditions import make_renditions
from app.modules.plans.router import router as plans_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole, TenantRole
from app.shared.storage import PresignedUpload, StorageObjectMissingError
from tests.integration.farms.conftest import build_app, make_context
from tests.integration.farms.test_block_crops import _multipolygon, _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "orange").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeStorage:
    bucket = "uploads"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def presign_upload(self, **kwargs: Any) -> PresignedUpload:
        return PresignedUpload(
            url=f"https://s3.test/{kwargs['key']}",
            headers={"Content-Type": kwargs["content_type"]},
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def get_object(self, *, key: str) -> bytes:
        if key not in self.objects:
            raise StorageObjectMissingError(self.bucket, key)
        return self.objects[key][0]

    def head_object(self, *, key: str) -> dict[str, Any]:
        if key not in self.objects:
            raise StorageObjectMissingError(self.bucket, key)
        body, content_type = self.objects[key]
        return {"ContentLength": len(body), "ContentType": content_type}


@pytest.mark.asyncio
async def test_image_key_must_live_under_the_crop_image_prefix(
    admin_session: AsyncSession,
) -> None:
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(
                "UPDATE public.crops SET image_s3_key = 'tenants/x/secret.png' "
                "WHERE code = 'olive'"
            )
        )
    await admin_session.rollback()


async def _upload(c: AsyncClient, storage: FakeStorage, path: str) -> dict[str, Any]:
    png = _png()
    r = await c.post(
        f"{path}/upload-init", json={"content_type": "image/png", "size_bytes": len(png)}
    )
    assert r.status_code == 200, r.text
    init = r.json()
    assert init["upload_headers"]["Content-Type"] == "image/png"
    storage.put_object(key=init["s3_key"], body=png, content_type="image/png")
    r = await c.post(f"{path}/finalize", json={"s3_key": init["s3_key"]})
    assert r.status_code == 200, r.text
    return {**r.json(), "s3_key": init["s3_key"]}


@pytest.mark.asyncio
async def test_upload_renditions_and_urls_end_to_end(  # noqa: PLR0915 - one story, end to end
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr(crop_images_service, "get_storage_client", lambda: storage)
    # The worker's task body, run inline instead of through the broker.
    enqueued: list[str] = []

    def _enqueue(key: str) -> None:
        enqueued.append(key)
        make_renditions(storage, key)  # type: ignore[arg-type]

    monkeypatch.setattr(crop_images_router, "_enqueue_renditions", _enqueue)

    admin = build_app(
        make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    )
    admin.include_router(crop_images_router.router)
    code = f"it_img_{uuid4().hex[:8]}"
    async with AsyncClient(transport=ASGITransport(app=admin), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Image test crop",
                "name_ar": "محصول اختبار الصورة",
                "category": "fruit_tree",
                "is_perennial": True,
                "classification_depth": "variety",
            },
        )
        assert r.status_code == 201, r.text
        crop = r.json()
        assert crop["crop_image_url"] is None
        r = await c.post(
            f"/api/v1/admin/crops/{crop['id']}/varieties",
            json={"code": "plain", "name_en": "Plain", "name_ar": "عادي"},
        )
        assert r.status_code == 201, r.text
        plain = r.json()
        r = await c.post(
            f"/api/v1/admin/crops/{crop['id']}/varieties",
            json={"code": "fancy", "name_en": "Fancy", "name_ar": "مميز"},
        )
        assert r.status_code == 201, r.text
        fancy = r.json()

        # Wrong type and unknown crop are refused before anything is signed.
        r = await c.post(
            f"/api/v1/admin/crops/{crop['id']}/image/upload-init",
            json={"content_type": "image/gif", "size_bytes": 10},
        )
        assert r.status_code == 422, r.text
        r = await c.post(
            f"/api/v1/admin/crops/{uuid4()}/image/upload-init",
            json={"content_type": "image/png", "size_bytes": 10},
        )
        assert r.status_code == 404, r.text

        crop_upload = await _upload(c, storage, f"/api/v1/admin/crops/{crop['id']}/image")
        fancy_upload = await _upload(
            c, storage, f"/api/v1/admin/crop-varieties/{fancy['id']}/image"
        )
        assert enqueued == [crop_upload["s3_key"], fancy_upload["s3_key"]]

        # A crop's key cannot be finalized onto a variety.
        r = await c.post(
            f"/api/v1/admin/crop-varieties/{plain['id']}/image/finalize",
            json={"s3_key": crop_upload["s3_key"]},
        )
        assert r.status_code == 422, r.text

        # The catalogue: the crop's own image; varieties resolve override first.
        crops = (await c.get("/api/v1/admin/crops")).json()
        listed = next(x for x in crops if x["id"] == crop["id"])
        assert listed["crop_image_url"] == crop_upload["crop_image_url"]
        assert listed["crop_icon_url"].endswith("/64.webp")
        varieties = {
            v["code"]: v
            for v in (await c.get(f"/api/v1/admin/crops/{crop['id']}/varieties")).json()
        }
        assert varieties["plain"]["crop_image_url"] == crop_upload["crop_image_url"]
        assert varieties["plain"]["has_own_image"] is False
        assert varieties["fancy"]["crop_image_url"] == fancy_upload["crop_image_url"]
        assert varieties["fancy"]["has_own_image"] is True

        # The public route serves the rendition without a token, cached for a year.
        path = crop_upload["crop_icon_url"].split("://", 1)[1].split("/", 1)[1]
        r = await c.get(f"/{path}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/webp"
        assert "immutable" in r.headers["cache-control"]
        with Image.open(io.BytesIO(r.content)) as image:
            assert image.size == (64, 64)
        # A size the worker never writes, and an image that does not exist.
        r = await c.get(f"/{path.replace('/64.webp', '/512.webp')}")
        assert r.status_code == 404
        r = await c.get(f"/api/v1/public/crop-images/crops/{crop['id']}/{uuid4()}/64.webp")
        assert r.status_code == 404
        assert r.headers["cache-control"] == "no-store"

    # Tenant side: block crop reads and the board carry the resolved image.
    slug = f"ci-{uuid4().hex[:6]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    owner = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_OWNER
        )
    )
    owner.include_router(plans_router)
    async with AsyncClient(transport=ASGITransport(app=owner), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/farms",
            json={"code": "CI-1", "name": "Images", "boundary": _multipolygon(31.3, 30.1)},
        )
        assert r.status_code == 201, r.text
        farm_id = r.json()["id"]
        block_ids = []
        for i, variety in enumerate((plain, fancy)):
            r = await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": f"B-{i}", "boundary": _polygon(31.3 + i * 0.002, 30.1)},
            )
            assert r.status_code == 201, r.text
            block_id = r.json()["id"]
            block_ids.append(block_id)
            r = await c.post(
                f"/api/v1/blocks/{block_id}/crop-assignments",
                json={
                    "crop_id": crop["id"],
                    "crop_variety_id": variety["id"],
                    "season_label": "2026",
                    "planting_date": "2020-01-01",
                },
            )
            assert r.status_code == 201, r.text

        r = await c.get(f"/api/v1/blocks/{block_ids[1]}/crop-assignments")
        assert r.status_code == 200, r.text
        assert r.json()[0]["crop_image_url"] == fancy_upload["crop_image_url"]

        r = await c.get(
            f"/api/v1/farms/{farm_id}/board",
            params={"week_start": date.today().isoformat(), "weeks": 1},
        )
        assert r.status_code == 200, r.text
        by_code = {b["code"]: b for b in r.json()["blocks"]}
        assert by_code["B-0"]["crop_icon_url"] == crop_upload["crop_icon_url"]
        assert by_code["B-1"]["crop_icon_url"] == fancy_upload["crop_icon_url"]
        assert "crop_image_key" not in by_code["B-0"]

    # Clearing the variety's image falls back to the crop's.
    async with AsyncClient(transport=ASGITransport(app=admin), base_url="http://test") as c:
        r = await c.delete(f"/api/v1/admin/crop-varieties/{fancy['id']}/image")
        assert r.status_code == 200, r.text
        varieties = {
            v["code"]: v
            for v in (await c.get(f"/api/v1/admin/crops/{crop['id']}/varieties")).json()
        }
        assert varieties["fancy"]["crop_image_url"] == crop_upload["crop_image_url"]
        assert varieties["fancy"]["has_own_image"] is False
