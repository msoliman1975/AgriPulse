"""Integration tests for CS-7 "undo a CSV import" (import batches).

Drives the upload → list-history → delete-batch flow end-to-end against
a live tenant schema:

  * POST /signals/csv-import returns an ``import_batch_id`` tagging the
    rows it just inserted.
  * GET /signals/import-batches lists that upload with the right
    ``row_count`` and signal codes.
  * DELETE /signals/import-batches/{id} removes every row of the upload
    and reports the count; the farm's observations are empty afterwards.

Reuses the farms-integration StubAuth + make_context pattern (no real
Keycloak): a TENANT_ADMIN context grants signal.read / signal.record /
signal.delete_observation tenant-wide.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.signals.router import router as signals_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(signals_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"Signals {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_resp = await client.post(
            "/api/v1/farms",
            json={
                "code": "SIG-FARM",
                "name": "CS-7 farm",
                "boundary": _square(31.70, 30.70),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm_resp.status_code == 201, farm_resp.text
        farm_id = farm_resp.json()["id"]
        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.71, 30.71)},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
        # A signal definition the CSV rows reference by code.
        def_resp = await client.post(
            "/api/v1/signals/definitions",
            json={
                "code": "soil_ph",
                "name": "Soil pH",
                "value_kind": "numeric",
                "value_min": "0",
                "value_max": "14",
            },
        )
        assert def_resp.status_code == 201, def_resp.text
    return context, farm_id, block_id


def _csv_bytes(rows: int) -> bytes:
    lines = ["signal_code,observed_at,value_numeric"]
    for i in range(rows):
        hour = f"{8 + i:02d}"
        lines.append(f"soil_ph,2026-05-18T{hour}:00:00+00:00,{6.0 + i * 0.1:.1f}")
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_import_then_list_then_delete_batch(admin_session: AsyncSession) -> None:
    context, farm_id, _block_id = await _bootstrap(admin_session, "cs7-undo")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Import a small CSV — response carries the import_batch_id.
        upload = await client.post(
            f"/api/v1/signals/csv-import?farm_id={farm_id}",
            files={"file": ("obs.csv", _csv_bytes(3), "text/csv")},
        )
        assert upload.status_code == 200, upload.text
        body = upload.json()
        assert body["rows_imported"] == 3
        batch_id = body["import_batch_id"]
        assert batch_id

        # 2. The import-history list surfaces exactly this upload.
        listed = await client.get(f"/api/v1/signals/import-batches?farm_id={farm_id}")
        assert listed.status_code == 200, listed.text
        batches = listed.json()
        assert len(batches) == 1
        assert batches[0]["import_batch_id"] == batch_id
        assert batches[0]["row_count"] == 3
        assert batches[0]["signal_codes"] == ["soil_ph"]

        # 3. Deleting the batch removes all 3 rows.
        deleted = await client.delete(
            f"/api/v1/signals/import-batches/{batch_id}?farm_id={farm_id}"
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": 3}

        # 4. No observations remain on the farm; history is empty.
        obs = await client.get(f"/api/v1/signals/observations?farm_id={farm_id}")
        assert obs.status_code == 200, obs.text
        assert obs.json() == []

        empty_history = await client.get(f"/api/v1/signals/import-batches?farm_id={farm_id}")
        assert empty_history.status_code == 200, empty_history.text
        assert empty_history.json() == []
