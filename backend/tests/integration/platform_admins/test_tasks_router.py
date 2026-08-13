"""The on-demand task trigger.

The interesting assertions here are all about what the endpoint *refuses*.
Dispatching a Celery task by name from an HTTP request is a remote code
execution primitive unless the allowlist holds, so these tests pin the
allowlist, the parameter validation, and — most importantly — that
``tenant_schema`` is taken from the resolved tenant and can never be supplied
by the caller.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.platform_admins.tasks_router import router as tasks_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole
from app.shared.keycloak import FakeKeycloakClient

from .conftest import StubAuth, make_context

pytestmark = [pytest.mark.integration]


class _FakeAsyncResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeCelery:
    """Records dispatches instead of performing them."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_task(self, name: str, kwargs: dict[str, Any], queue: str) -> _FakeAsyncResult:
        self.sent.append({"name": name, "kwargs": kwargs, "queue": queue})
        return _FakeAsyncResult(f"task-{len(self.sent)}")


@pytest.fixture
def celery_stub(monkeypatch: pytest.MonkeyPatch) -> _FakeCelery:
    # The router imports `current_app` inside the request handler, so the
    # module attribute is resolved per call and patching it here takes effect.
    fake = _FakeCelery()
    monkeypatch.setattr("celery.current_app", fake, raising=False)
    return fake


def _client() -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(tasks_router)
    app.add_middleware(
        StubAuth,
        context=make_context(
            user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
        ),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _tenant(session: AsyncSession):
    service = get_tenant_service(session, keycloak_client=FakeKeycloakClient())
    return await service.create_tenant(
        slug=f"task-{uuid4().hex[:8]}",
        name="Task Trigger Test",
        contact_email="ops@task.test",
        actor_user_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_lists_triggerable_tasks_and_excludes_sweeps() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/admin/tasks")

    assert response.status_code == 200
    names = [t["name"] for t in response.json()["tasks"]]
    assert "recommendations.evaluate_for_tenant" in names
    # A sweep walks every active tenant, so exposing one would let a run
    # against a throwaway tenant write into every other tenant on the platform.
    assert not [n for n in names if n.endswith("_sweep")]
    assert "purge.run_job" not in names


@pytest.mark.asyncio
async def test_dispatches_with_schema_from_the_resolved_tenant(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run",
            json={"tenant_slug": tenant.slug},
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["tenant_slug"] == tenant.slug
    assert body["task_id"]
    sent = celery_stub.sent
    assert len(sent) == 1
    assert sent[0]["name"] == "recommendations.evaluate_for_tenant"
    assert sent[0]["queue"] == "light"
    assert sent[0]["kwargs"] == {"tenant_schema": tenant.schema_name}


@pytest.mark.asyncio
async def test_caller_cannot_supply_tenant_schema(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    """The one parameter that must never be caller-controlled.

    If it were accepted, naming any tenant's schema in ``params`` would aim a
    task at a tenant the caller did not identify in the body — and the audit
    row would record the wrong one.
    """
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run",
            json={
                "tenant_slug": tenant.slug,
                "params": {"tenant_schema": "tenant_someone_else"},
            },
        )

    assert response.status_code == 422
    assert not celery_stub.sent


@pytest.mark.asyncio
async def test_unknown_task_is_refused(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/purge.run_job:run",
            json={"tenant_slug": tenant.slug},
        )

    assert response.status_code == 404
    assert not celery_stub.sent


@pytest.mark.asyncio
async def test_missing_required_param_is_refused(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/weather.derive_weather_daily:run",
            json={"tenant_slug": tenant.slug},
        )

    assert response.status_code == 422
    assert "farm_id" in response.text
    assert not celery_stub.sent


@pytest.mark.asyncio
async def test_optional_param_is_forwarded(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/weather.compute_spi_for_tenant:run",
            json={"tenant_slug": tenant.slug, "params": {"target_iso": "2026-06-01"}},
        )

    assert response.status_code == 202, response.text
    assert celery_stub.sent[0]["kwargs"] == {
        "tenant_schema": tenant.schema_name,
        "target_iso": "2026-06-01",
    }


@pytest.mark.asyncio
async def test_requires_exactly_one_tenant_identifier(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    tenant = await _tenant(admin_session)
    await admin_session.commit()

    async with _client() as client:
        neither = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run", json={}
        )
        both = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run",
            json={"tenant_slug": tenant.slug, "tenant_id": str(tenant.tenant_id)},
        )

    assert neither.status_code == 422
    assert both.status_code == 422
    assert not celery_stub.sent


@pytest.mark.asyncio
async def test_suspended_tenant_is_refused(
    admin_session: AsyncSession, celery_stub: _FakeCelery
) -> None:
    """A tenant taken out of service must not have work written into it."""
    tenant = await _tenant(admin_session)
    await admin_session.execute(
        text("UPDATE public.tenants SET status = 'suspended' WHERE id = :id"),
        {"id": tenant.tenant_id},
    )
    await admin_session.commit()

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run",
            json={"tenant_slug": tenant.slug},
        )

    assert response.status_code == 409
    assert not celery_stub.sent


@pytest.mark.asyncio
async def test_unknown_tenant_is_refused(celery_stub: _FakeCelery) -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/tasks/recommendations.evaluate_for_tenant:run",
            json={"tenant_slug": "no-such-tenant"},
        )

    assert response.status_code == 404
    assert not celery_stub.sent
