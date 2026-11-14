"""D29 on Postgres: editions, the deferred supersede, inheritance, the block routes.

Storage is faked (no S3 in CI); everything else is real -- the migration's
constraints, the partial unique index on the current edition, the deferred
`superseded_by` foreign key, and the block's current crop path read through
the farms module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crop_documents import router as crop_documents_router
from app.modules.crop_documents.schemas import CropDocumentFields
from app.modules.crop_documents.service import CropDocumentsService
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, PlatformRole, TenantRole
from app.shared.db.session import get_admin_db_session
from app.shared.storage import PresignedDownload
from tests.integration.farms.conftest import build_app, make_context
from tests.integration.farms.test_block_crops import _multipolygon, _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]

PDF = b"%PDF-1.7\n" + b"x" * 64


class FakeStorage:
    bucket = "uploads"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = body

    def presign_download(self, **kwargs: Any) -> PresignedDownload:
        return PresignedDownload(
            url=f"https://s3.test/{kwargs['key']}",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )


def _fields(code: str, **overrides: Any) -> CropDocumentFields:
    base: dict[str, Any] = {
        "crop_path": "date_palm.medjool",
        "document_code": code,
        "title_en": "Organic Medjool Manual",
        "title_ar": "دليل المجهول العضوي",
        "language": "en",
        "kind": "manual",
        "edition": "1.3",
    }
    return CropDocumentFields(**{**base, **overrides})


@pytest.mark.asyncio
async def test_new_edition_supersedes_in_one_transaction(admin_session: AsyncSession) -> None:
    storage = FakeStorage()
    service = CropDocumentsService(admin_session, storage=storage)  # type: ignore[arg-type]
    code = f"it_manual_{uuid4().hex[:8]}"

    first = await service.upload(_fields(code), filename="m-1.3.pdf", body=PDF, actor=None)
    second = await service.upload(
        _fields(code, edition="1.7"), filename="m-1.7.pdf", body=PDF, actor=None
    )
    # The deferred foreign key is checked here.
    await admin_session.commit()

    assert second["superseded_id"] == first["id"]
    rows = {
        r["edition"]: r
        for r in await service.list_for_admin("date_palm.medjool")
        if r["document_code"] == code
    }
    assert rows["1.3"]["superseded_by"] == second["id"]
    assert rows["1.3"]["superseded_at"] is not None
    assert rows["1.3"]["is_current"] is False
    assert rows["1.7"]["is_current"] is True
    assert len(storage.objects) == 2


@pytest.mark.asyncio
async def test_only_one_current_edition_per_code(admin_session: AsyncSession) -> None:
    code = f"it_dup_{uuid4().hex[:8]}"
    insert = text(
        "INSERT INTO public.crop_documents (document_code, crop_path, title_en, title_ar, "
        "language, kind, edition, s3_key, original_filename, content_type, size_bytes, sha256) "
        "VALUES (:c, 'date_palm', 't', 'ع', 'en', 'manual', '1', :k, 'f.pdf', "
        "'application/pdf', 1, repeat('a', 64))"
    )
    await admin_session.execute(insert, {"c": code, "k": f"k/{uuid4()}"})
    with pytest.raises(IntegrityError):
        await admin_session.execute(insert, {"c": code, "k": f"k/{uuid4()}"})
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_arabic_title_is_required_by_the_table(admin_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(
                "INSERT INTO public.crop_documents (document_code, crop_path, title_en, "
                "title_ar, language, kind, edition, s3_key, original_filename, content_type, "
                "size_bytes, sha256) VALUES ('x', 'date_palm', 't', ' ', 'en', 'manual', '1', "
                ":k, 'f.pdf', 'application/pdf', 1, repeat('a', 64))"
            ),
            {"k": f"k/{uuid4()}"},
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_inherited_documents_reach_the_block(admin_session: AsyncSession) -> None:
    storage = FakeStorage()

    def _service(session: AsyncSession = Depends(get_admin_db_session)) -> CropDocumentsService:
        return CropDocumentsService(session, storage=storage)  # type: ignore[arg-type]

    # Documents: one on the crop the block grows, one on another crop.
    service = CropDocumentsService(admin_session, storage=storage)  # type: ignore[arg-type]
    olive_code = f"it_olive_{uuid4().hex[:8]}"
    olive = await service.upload(
        _fields(olive_code, crop_path="olive", kind="guide"),
        filename="olive.pdf",
        body=PDF,
        actor=None,
    )
    await service.upload(
        _fields(f"it_palm_{uuid4().hex[:8]}", crop_path="date_palm"),
        filename="palm.pdf",
        body=PDF,
        actor=None,
    )
    await admin_session.commit()

    slug = f"cd-{uuid4().hex[:6]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    owner_app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_OWNER
        )
    )
    owner_app.include_router(crop_documents_router.router)
    owner_app.dependency_overrides[crop_documents_router._service] = _service

    async with AsyncClient(transport=ASGITransport(app=owner_app), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/farms",
            json={"code": "CD-1", "name": "Docs", "boundary": _multipolygon(31.2, 30.0)},
        )
        assert r.status_code == 201, r.text
        farm_id = r.json()["id"]
        r = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-1", "boundary": _polygon(31.2, 30.0)},
        )
        assert r.status_code == 201, r.text
        block_id = r.json()["id"]

        # No crop yet: nothing to show.
        r = await c.get(f"/api/v1/blocks/{block_id}/crop-documents")
        assert r.status_code == 200, r.text
        assert r.json() == {"block_id": block_id, "crop_path": None, "documents": []}

        crops = (await c.get("/api/v1/crops")).json()
        olive_id = next(x["id"] for x in crops if x["code"] == "olive")
        r = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={"crop_id": olive_id, "season_label": "2026", "planting_date": "2019-03-04"},
        )
        assert r.status_code == 201, r.text

        r = await c.get(f"/api/v1/blocks/{block_id}/crop-documents")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["crop_path"] == "olive"
        assert [d["id"] for d in body["documents"]] == [str(olive["id"])]

        r = await c.get(
            f"/api/v1/blocks/{block_id}/crop-documents/{olive['id']}/link",
            params={"disposition": "inline"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["disposition"] == "inline"

    # A farm manager on the same farm does not hold the capability by default.
    manager_app = build_app(
        make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.FARM_MANAGER),),
        )
    )
    manager_app.include_router(crop_documents_router.router)
    manager_app.dependency_overrides[crop_documents_router._service] = _service
    async with AsyncClient(transport=ASGITransport(app=manager_app), base_url="http://test") as c:
        r = await c.get(f"/api/v1/blocks/{block_id}/crop-documents")
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_admin_upload_route_is_multipart(admin_session: AsyncSession) -> None:
    storage = FakeStorage()

    def _service(session: AsyncSession = Depends(get_admin_db_session)) -> CropDocumentsService:
        return CropDocumentsService(session, storage=storage)  # type: ignore[arg-type]

    app = build_app(
        make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    )
    app.include_router(crop_documents_router.router)
    app.dependency_overrides[crop_documents_router._service] = _service
    code = f"it_route_{uuid4().hex[:8]}"
    form = {
        "crop_path": "date_palm.medjool",
        "document_code": code,
        "title_en": "Medjool Decision Trees",
        "title_ar": "أشجار القرار للمجهول",
        "language": "en",
        "kind": "guide",
        "edition": "v2",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/admin/crop-documents",
            data=form,
            files={"file": ("trees-v2.pdf", PDF, "application/pdf")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["title_ar"] == form["title_ar"]

        r = await c.post(
            "/api/v1/admin/crop-documents",
            data={**form, "crop_path": "date_palm.not_a_variety"},
            files={"file": ("trees-v2.pdf", PDF, "application/pdf")},
        )
        assert r.status_code == 404, r.text

        r = await c.get("/api/v1/admin/crop-documents", params={"crop_path": "date_palm.medjool"})
        assert r.status_code == 200, r.text
        assert code in {d["document_code"] for d in r.json()}
