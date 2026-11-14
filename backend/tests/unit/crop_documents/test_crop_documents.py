"""D29: crop documents -- validation, editions, inheritance, links, routes.

No database: the service runs over an in-memory repository and a fake
storage client, and the routes over the same with stubbed auth. The SQL
itself is covered by tests/integration/crop_documents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import unquote
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.crop_documents import router as router_module
from app.modules.crop_documents.repository import path_chain
from app.modules.crop_documents.schemas import (
    MAX_DOCUMENT_BYTES,
    CropDocumentFields,
    CropDocumentUpdateRequest,
    content_type_for,
)
from app.modules.crop_documents.service import (
    CropDocumentNotFoundError,
    CropDocumentsService,
    UnknownCropPathError,
    UnsupportedFileError,
)
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.rbac.check import get_default_registry
from app.shared.storage import PresignedDownload, build_crop_document_key, content_disposition

PDF = b"%PDF-1.7\n" + b"x" * 100
KNOWN_PATHS = {"date_palm", "date_palm.medjool", "date_palm.barhee"}


# ---- Fakes ------------------------------------------------------------------


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self._tick = 0

    def _now(self) -> datetime:
        self._tick += 1
        return datetime(2026, 11, 14, tzinfo=UTC) + timedelta(seconds=self._tick)

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "is_current": row["superseded_at"] is None and row["retired_at"] is None,
        }

    async def crop_path_exists(self, crop_path: str) -> bool:
        return crop_path in KNOWN_PATHS

    async def get(self, document_id: UUID) -> dict[str, Any] | None:
        row = self.rows.get(document_id)
        return self._view(row) if row else None

    async def current_for(self, *, crop_path: str, document_code: str) -> dict[str, Any] | None:
        for row in self.rows.values():
            if (
                row["crop_path"] == crop_path
                and row["document_code"] == document_code
                and row["superseded_at"] is None
            ):
                return self._view(row)
        return None

    async def supersede(self, *, document_id: UUID, by: UUID, actor: UUID | None) -> None:
        self.rows[document_id].update(superseded_at=self._now(), superseded_by=by)

    async def insert(self, row: dict[str, Any], actor: UUID | None) -> None:
        # The partial unique index: one current row per (path, code).
        assert (
            await self.current_for(crop_path=row["crop_path"], document_code=row["document_code"])
            is None
        )
        now = self._now()
        self.rows[row["id"]] = {
            **row,
            "superseded_at": None,
            "superseded_by": None,
            "retired_at": None,
            "created_at": now,
            "updated_at": now,
        }

    async def update(
        self, document_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any] | None:
        row = self.rows.get(document_id)
        if row is None:
            return None
        for key, value in fields.items():
            if key == "retired":
                row["retired_at"] = (row["retired_at"] or self._now()) if value else None
            else:
                row[key] = value
        return self._view(row)

    async def list_for_admin(self, crop_path: str) -> list[dict[str, Any]]:
        ancestors = path_chain(crop_path)[:-1]
        return [
            self._view(r)
            for r in self.rows.values()
            if r["crop_path"] == crop_path
            or (r["crop_path"] in ancestors and self._view(r)["is_current"])
        ]

    async def list_current_for_path(self, crop_path: str) -> list[dict[str, Any]]:
        chain = path_chain(crop_path)
        return [
            self._view(r)
            for r in self.rows.values()
            if r["crop_path"] in chain and self._view(r)["is_current"]
        ]


class FakeStorage:
    bucket = "uploads"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.presigned: list[dict[str, Any]] = []

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def presign_download(self, **kwargs: Any) -> PresignedDownload:
        self.presigned.append(kwargs)
        return PresignedDownload(
            url=f"https://s3.test/{kwargs['key']}?sig=1",
            expires_at=datetime(2026, 11, 14, 0, 5, tzinfo=UTC),
        )


class FakeLookup:
    def __init__(self, farm_id: UUID, crop_path: str | None) -> None:
        self.farm_id = farm_id
        self.crop_path = crop_path

    async def farm_id_of(self, block_id: UUID) -> UUID:
        return self.farm_id

    async def current_crop_path(self, block_id: UUID) -> str | None:
        return self.crop_path


def _fields(**overrides: Any) -> CropDocumentFields:
    base: dict[str, Any] = {
        "crop_path": "date_palm.medjool",
        "document_code": "medjool_organic_manual_en",
        "title_en": "Organic Medjool Manual",
        "title_ar": "دليل المجهول العضوي",
        "language": "en",
        "kind": "manual",
        "edition": "1.7",
    }
    return CropDocumentFields(**{**base, **overrides})


def _service() -> tuple[CropDocumentsService, FakeRepo, FakeStorage]:
    repo, storage = FakeRepo(), FakeStorage()
    return CropDocumentsService(repository=repo, storage=storage), repo, storage  # type: ignore[arg-type]


# ---- Pure helpers -----------------------------------------------------------


def test_path_chain_is_ancestors_on_segment_boundaries() -> None:
    assert path_chain("date_palm.medjool") == ["date_palm", "date_palm.medjool"]
    assert path_chain("mango.alphonso.short") == [
        "mango",
        "mango.alphonso",
        "mango.alphonso.short",
    ]
    assert path_chain("cotton") == ["cotton"]


def test_content_type_follows_the_extension() -> None:
    assert content_type_for("Manual 1.7.PDF") == "application/pdf"
    assert (content_type_for("trees.docx") or "").startswith("application/vnd.openxmlformats")
    assert content_type_for("setup.exe") is None
    assert content_type_for("no_extension") is None


def test_key_is_platform_scoped_and_safe() -> None:
    doc_id = UUID("01930000-0000-7000-8000-000000000001")
    key = build_crop_document_key(document_id=doc_id, original_filename="دليل المجهول 1.7.pdf")
    assert key.startswith(f"platform/crop-documents/{doc_id}/")
    assert not key.startswith("tenants/")
    assert key.endswith(".pdf")


def test_content_disposition_carries_an_arabic_name() -> None:
    value = content_disposition("دليل المجهول.pdf", inline=False)
    assert value.startswith('attachment; filename="')
    encoded = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "دليل المجهول.pdf"
    assert content_disposition('a"b.pdf', inline=True).startswith('inline; filename="a_b.pdf"')


# ---- Validation -------------------------------------------------------------


def test_arabic_title_is_required() -> None:
    with pytest.raises(ValidationError):
        _fields(title_ar="   ")
    with pytest.raises(ValidationError):
        _fields(title_en="")


@pytest.mark.parametrize("code", ["Medjool", "_x", "a b", "x" * 101, ""])
def test_document_code_shape(code: str) -> None:
    with pytest.raises(ValidationError):
        _fields(document_code=code)


def test_kind_and_language_are_closed_lists() -> None:
    with pytest.raises(ValidationError):
        _fields(kind="brochure")
    with pytest.raises(ValidationError):
        _fields(language="fr")
    assert _fields(language="other").language == "other"


def test_update_rejects_null_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CropDocumentUpdateRequest.model_validate({"title_ar": None})
    with pytest.raises(ValidationError):
        CropDocumentUpdateRequest.model_validate({"crop_path": "mango"})
    req = CropDocumentUpdateRequest.model_validate({"retired": True, "edition": " 1.7a "})
    assert req.model_dump(exclude_unset=True) == {"retired": True, "edition": "1.7a"}


# ---- Service ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_stores_the_file_and_records_it() -> None:
    service, repo, storage = _service()
    created = await service.upload(_fields(), filename="Manual 1.7.pdf", body=PDF, actor=None)
    assert created["superseded_id"] is None
    assert created["is_current"] is True
    assert created["content_type"] == "application/pdf"
    assert created["size_bytes"] == len(PDF)
    assert len(created["sha256"]) == 64
    assert "s3_key" not in created
    (key,) = storage.objects
    assert repo.rows[created["id"]]["s3_key"] == key
    assert storage.objects[key] == (PDF, "application/pdf")


@pytest.mark.asyncio
async def test_new_edition_supersedes_and_keeps_history() -> None:
    service, repo, _ = _service()
    first = await service.upload(
        _fields(edition="1.3"), filename="manual-1.3.pdf", body=PDF, actor=None
    )
    second = await service.upload(_fields(), filename="manual-1.7.pdf", body=PDF, actor=None)
    assert second["superseded_id"] == first["id"]
    old = repo.rows[first["id"]]
    assert old["superseded_by"] == second["id"]
    assert old["superseded_at"] is not None
    # History stays: both editions are listed for the admin, one is current.
    listed = await service.list_for_admin("date_palm.medjool")
    assert {d["edition"]: d["is_current"] for d in listed} == {"1.3": False, "1.7": True}
    # Another code at the same path is a separate document, not an edition.
    ar = await service.upload(
        _fields(document_code="medjool_organic_manual_ar", language="ar"),
        filename="manual-ar.pdf",
        body=PDF,
        actor=None,
    )
    assert ar["superseded_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "body"),
    [("tool.exe", PDF), ("manual.pdf", b""), ("manual.pdf", b"x" * (MAX_DOCUMENT_BYTES + 1))],
)
async def test_upload_rejects_bad_files_before_storing(filename: str, body: bytes) -> None:
    service, repo, storage = _service()
    with pytest.raises(UnsupportedFileError):
        await service.upload(_fields(), filename=filename, body=body, actor=None)
    assert not storage.objects
    assert not repo.rows


@pytest.mark.asyncio
async def test_upload_needs_a_catalogue_path() -> None:
    service, _, storage = _service()
    with pytest.raises(UnknownCropPathError):
        await service.upload(
            _fields(crop_path="date_palm.nope"), filename="m.pdf", body=PDF, actor=None
        )
    assert not storage.objects


@pytest.mark.asyncio
async def test_block_sees_documents_inherited_down_the_path() -> None:
    service, _, _ = _service()
    crop_doc = await service.upload(
        _fields(crop_path="date_palm", document_code="date_palm_guide", kind="guide"),
        filename="guide.pdf",
        body=PDF,
        actor=None,
    )
    medjool = await service.upload(_fields(), filename="m.pdf", body=PDF, actor=None)
    await service.upload(
        _fields(crop_path="date_palm.barhee", document_code="barhee_manual"),
        filename="b.pdf",
        body=PDF,
        actor=None,
    )
    farm = uuid4()

    out = await service.for_block(uuid4(), FakeLookup(farm, "date_palm.medjool"))
    assert {d["id"] for d in out["documents"]} == {crop_doc["id"], medjool["id"]}
    assert out["crop_path"] == "date_palm.medjool"

    # The crop-level document reaches a crop-level block; a variety's does not.
    top = await service.for_block(uuid4(), FakeLookup(farm, "date_palm"))
    assert [d["id"] for d in top["documents"]] == [crop_doc["id"]]

    # A block with no current crop shows nothing.
    assert (await service.for_block(uuid4(), FakeLookup(farm, None)))["documents"] == []


@pytest.mark.asyncio
async def test_retired_and_superseded_documents_leave_the_block() -> None:
    service, _, _ = _service()
    old = await service.upload(_fields(edition="1.3"), filename="a.pdf", body=PDF, actor=None)
    new = await service.upload(_fields(), filename="b.pdf", body=PDF, actor=None)
    lookup = FakeLookup(uuid4(), "date_palm.medjool")
    assert [d["id"] for d in (await service.for_block(uuid4(), lookup))["documents"]] == [new["id"]]
    with pytest.raises(CropDocumentNotFoundError):
        await service.block_link(uuid4(), old["id"], "attachment", lookup)

    retired = await service.update(new["id"], {"retired": True}, None)
    assert retired["is_current"] is False
    assert (await service.for_block(uuid4(), lookup))["documents"] == []
    restored = await service.update(new["id"], {"retired": False}, None)
    assert restored["is_current"] is True


@pytest.mark.asyncio
async def test_links_are_short_lived_and_view_falls_back_to_download() -> None:
    service, _, storage = _service()
    pdf = await service.upload(_fields(), filename="manual.pdf", body=PDF, actor=None)
    docx = await service.upload(
        _fields(document_code="medjool_trees_en", kind="guide"),
        filename="trees.docx",
        body=b"PK\x03\x04docx",
        actor=None,
    )
    lookup = FakeLookup(uuid4(), "date_palm.medjool")

    view = await service.block_link(uuid4(), pdf["id"], "inline", lookup)
    assert view["disposition"] == "inline"
    assert storage.presigned[-1]["expires_seconds"] == 300
    assert storage.presigned[-1]["response_content_disposition"].startswith("inline;")
    assert storage.presigned[-1]["response_content_type"] == "application/pdf"

    # A browser cannot render a .docx, so "view" downloads it.
    assert (await service.block_link(uuid4(), docx["id"], "inline", lookup))[
        "disposition"
    ] == "attachment"

    # A document the block does not show is not reachable through the block.
    other = await service.upload(
        _fields(crop_path="date_palm.barhee", document_code="barhee"),
        filename="b.pdf",
        body=PDF,
        actor=None,
    )
    with pytest.raises(CropDocumentNotFoundError):
        await service.block_link(uuid4(), other["id"], "attachment", lookup)
    # The admin link reaches any document.
    assert (await service.admin_link(other["id"], "attachment"))["url"].startswith("https://")


# ---- RBAC -------------------------------------------------------------------


def test_download_is_granted_to_tenant_owner_and_admin_only_by_default() -> None:
    registry = get_default_registry()
    assert registry.known("crop_document.download")
    holders = {role for role, caps in registry.roles().items() if "crop_document.download" in caps}
    assert holders == {"TenantOwner", "TenantAdmin"}


# ---- Routes -----------------------------------------------------------------


class _StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            Request(scope, receive=receive).state.context = self._context
        await self._app(scope, receive, send)


def _context(
    *,
    tenant_role: TenantRole | None = None,
    platform_role: PlatformRole | None = None,
    farm_scopes: tuple[FarmScope, ...] = (),
    tenant: bool = True,
) -> RequestContext:
    user_id = uuid4()
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=uuid4() if tenant else None,
        tenant_role=tenant_role,
        platform_role=platform_role,
        farm_scopes=farm_scopes,
    )


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    fake = AsyncMock()
    monkeypatch.setattr(router_module, "get_audit_service", lambda: fake)
    return fake


def _app(context: RequestContext, service: CropDocumentsService, lookup: FakeLookup) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router_module.router)
    app.dependency_overrides[router_module._service] = lambda: service
    app.dependency_overrides[router_module._lookup] = lambda: lookup
    app.add_middleware(_StubAuth, context=context)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_FORM = {
    "crop_path": "date_palm.medjool",
    "document_code": "medjool_organic_manual_en",
    "title_en": "Organic Medjool Manual",
    "title_ar": "دليل المجهول العضوي",
    "language": "en",
    "kind": "manual",
    "edition": "1.7",
}


@pytest.mark.asyncio
async def test_platform_admin_uploads_multipart(audit: AsyncMock) -> None:
    service, _, _ = _service()
    app = _app(
        _context(platform_role=PlatformRole.PLATFORM_ADMIN, tenant=False),
        service,
        FakeLookup(uuid4(), None),
    )
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/crop-documents",
            data=_FORM,
            files={"file": ("Manual 1.7.pdf", PDF, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title_ar"] == _FORM["title_ar"]
        assert body["superseded_id"] is None
        assert "s3_key" not in body
        audit.record_archive.assert_awaited_once()
        assert (
            audit.record_archive.await_args.kwargs["event_type"]
            == "platform.crop_document_uploaded"
        )

        resp = await c.post(
            "/api/v1/admin/crop-documents",
            data={**_FORM, "title_ar": " "},
            files={"file": ("m.pdf", PDF, "application/pdf")},
        )
        assert resp.status_code == 422, resp.text

        resp = await c.post(
            "/api/v1/admin/crop-documents",
            data=_FORM,
            files={"file": ("m.exe", PDF, "application/octet-stream")},
        )
        assert resp.status_code == 422, resp.text

        resp = await c.get(
            "/api/v1/admin/crop-documents", params={"crop_path": "date_palm.medjool"}
        )
        assert resp.status_code == 200
        assert [d["edition"] for d in resp.json()] == ["1.7"]

        resp = await c.patch(
            f"/api/v1/admin/crop-documents/{body['id']}", json={"edition": "1.7.1"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["edition"] == "1.7.1"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_upload(audit: AsyncMock) -> None:
    service, repo, _ = _service()
    app = _app(_context(tenant_role=TenantRole.TENANT_ADMIN), service, FakeLookup(uuid4(), None))
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/crop-documents",
            data=_FORM,
            files={"file": ("m.pdf", PDF, "application/pdf")},
        )
    assert resp.status_code == 403
    assert not repo.rows
    audit.record_archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_block_routes_follow_the_download_capability() -> None:
    service, _, _ = _service()
    doc = await service.upload(_fields(), filename="manual.pdf", body=PDF, actor=None)
    farm = uuid4()
    lookup = FakeLookup(farm, "date_palm.medjool")
    block = uuid4()

    owner = _app(_context(tenant_role=TenantRole.TENANT_OWNER), service, lookup)
    async with _client(owner) as c:
        resp = await c.get(f"/api/v1/blocks/{block}/crop-documents")
        assert resp.status_code == 200, resp.text
        assert [d["id"] for d in resp.json()["documents"]] == [str(doc["id"])]
        resp = await c.get(
            f"/api/v1/blocks/{block}/crop-documents/{doc['id']}/link",
            params={"disposition": "inline"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["disposition"] == "inline"
        resp = await c.get(f"/api/v1/blocks/{block}/crop-documents/{uuid4()}/link")
        assert resp.status_code == 404

    # A farm manager does not hold it by default: the block reads as absent.
    manager = _app(
        _context(farm_scopes=(FarmScope(farm_id=farm, role=FarmRole.FARM_MANAGER),)),
        service,
        lookup,
    )
    async with _client(manager) as c:
        resp = await c.get(f"/api/v1/blocks/{block}/crop-documents")
        assert resp.status_code == 404
        resp = await c.get(f"/api/v1/blocks/{block}/crop-documents/{doc['id']}/link")
        assert resp.status_code == 404

    # No tenant in the token: refused before any lookup.
    platform = _app(
        _context(platform_role=PlatformRole.PLATFORM_SUPPORT, tenant=False), service, lookup
    )
    async with _client(platform) as c:
        resp = await c.get(f"/api/v1/blocks/{block}/crop-documents")
        assert resp.status_code == 403
