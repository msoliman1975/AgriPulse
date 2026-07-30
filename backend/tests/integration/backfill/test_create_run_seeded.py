"""Backfill run submission against a tenant this module seeds itself.

The pre-existing tests in ``test_backfill_console.py`` all `pytest.skip` when
the fixture DB happens to have no tenant with an unoccupied farm, which is
the normal case — so POST /runs (the INSERT into public.backfill_runs and the
dispatch that follows it) was never actually executed in CI. A 500 on that
endpoint shipped to production undetected as a result.

These tests seed their own tenant + farm + block + subscriptions, so they
exercise the submit path unconditionally and can never silently skip.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def _fake_send_task(name: str, **kwargs: Any) -> None:
        sent.append({"name": name, **kwargs})

    from app.modules.backfill import service as svc

    monkeypatch.setattr(svc.celery_current_app, "send_task", _fake_send_task)
    return sent


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


@pytest.fixture
async def seeded_farm(admin_session: Any) -> dict[str, Any]:
    """A tenant with one farm, one block, and both subscription kinds.

    Seeded with SQL rather than the farms API because this package mounts
    only the backfill router.
    """
    slug = f"bf-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'BF', 'BF farm', "
            "ST_GeomFromText('POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))'"
            ", 4326))"
        ),
        {"id": str(farm_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) VALUES (:id, :fid, 'B1', "
            "'B1', ST_GeomFromText('POLYGON((31.201 30.001,31.205 30.001,31.205 30.005,"
            "31.201 30.005,31.201 30.001))', 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id)},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    await admin_session.execute(
        text(
            "INSERT INTO imagery_aoi_subscriptions (block_id, product_id, cadence_hours, "
            "is_active) VALUES (:bid, :pid, 24, TRUE)"
        ),
        {"bid": str(block_id), "pid": str(product_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO weather_subscriptions (block_id, provider_code, cadence_hours, "
            "is_active) VALUES (:bid, 'open_meteo', 6, TRUE)"
        ),
        {"bid": str(block_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"tenant_id": tenant.tenant_id, "farm_id": farm_id, "schema": schema}


@pytest.mark.asyncio
async def test_submitting_a_run_persists_it_and_dispatches(
    seeded_farm: dict[str, Any], sent_tasks: list[dict[str, Any]]
) -> None:
    """The regression: this endpoint 500'd in production."""
    tenant_id: UUID = seeded_farm["tenant_id"]
    body = {
        "farm_id": str(seeded_farm["farm_id"]),
        "window_from": (date.today() - timedelta(days=2)).isoformat(),
        "window_to": date.today().isoformat(),
        "imagery": True,
        "weather": True,
    }
    async with _platform_client() as client:
        created = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert created.status_code == 201, created.text
        run = created.json()
        assert run["status"] == "queued"
        assert run["sources"] == {"imagery": True, "weather": True}

        # The row must be readable back — the console renders from this list.
        listed = (await client.get("/api/v1/admin/backfill/runs")).json()
        assert any(r["id"] == run["id"] for r in listed)

    names = {s["name"] for s in sent_tasks}
    assert "imagery.backfill_farm_scenes" in names
    assert "weather.backfill_weather" in names


@pytest.mark.asyncio
async def test_indices_run_submits_too(
    seeded_farm: dict[str, Any], sent_tasks: list[dict[str, Any]]
) -> None:
    """The console's other button writes the same row, so it 500'd identically."""
    tenant_id: UUID = seeded_farm["tenant_id"]
    body = {
        "farm_id": str(seeded_farm["farm_id"]),
        "window_from": (date.today() - timedelta(days=5)).isoformat(),
        "window_to": date.today().isoformat(),
        "imagery": True,
        "weather": True,
        "kind": "indices",
    }
    async with _platform_client() as client:
        created = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert created.status_code == 201, created.text
        assert created.json()["kind"] == "indices"

    # Indices recompute over stored data — it must not re-fetch from providers.
    names = {s["name"] for s in sent_tasks}
    assert "imagery.backfill_farm_scenes" not in names
    assert "weather.backfill_weather" not in names


@pytest.mark.asyncio
async def test_source_without_subscriptions_is_refused_not_accepted(
    admin_session: Any, seeded_farm: dict[str, Any]
) -> None:
    """422 rather than a run that would fetch nothing and read as success."""
    await admin_session.execute(text(f'SET search_path TO "{seeded_farm["schema"]}", public'))
    await admin_session.execute(text("UPDATE weather_subscriptions SET is_active = FALSE"))
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    body = {
        "farm_id": str(seeded_farm["farm_id"]),
        "window_from": date.today().isoformat(),
        "window_to": date.today().isoformat(),
        "imagery": False,
        "weather": True,
    }
    async with _platform_client() as client:
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded_farm['tenant_id']}/runs", json=body
        )
        assert r.status_code == 422, r.text
        assert "weather" in r.json()["detail"]


@pytest.mark.asyncio
async def test_cancelling_a_stuck_run_frees_the_farm(seeded_farm: dict[str, Any]) -> None:
    """Without this the farm is blocked for good — see the hung-run incident."""
    tenant_id: UUID = seeded_farm["tenant_id"]
    body = {
        "farm_id": str(seeded_farm["farm_id"]),
        "window_from": date.today().isoformat(),
        "window_to": date.today().isoformat(),
        "imagery": False,
        "weather": True,
    }
    async with _platform_client() as client:
        run = (
            await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        ).json()
        # Farm is occupied, so a resubmit is refused.
        assert (
            await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        ).status_code == 409

        cancelled = await client.post(f"/api/v1/admin/backfill/runs/{run['id']}:cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "failed"
        assert cancelled.json()["completed_at"] is not None

        # Cancelling again is a clean 409, not a second mutation.
        second = await client.post(f"/api/v1/admin/backfill/runs/{run['id']}:cancel")
        assert second.status_code == 409, second.text

        # And the farm accepts work again.
        assert (
            await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        ).status_code == 201


@pytest.mark.asyncio
async def test_cancelling_an_unknown_run_is_404() -> None:
    async with _platform_client() as client:
        r = await client.post(f"/api/v1/admin/backfill/runs/{uuid4()}:cancel")
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_second_submit_for_the_same_farm_is_refused(
    seeded_farm: dict[str, Any],
) -> None:
    tenant_id: UUID = seeded_farm["tenant_id"]
    body = {
        "farm_id": str(seeded_farm["farm_id"]),
        "window_from": date.today().isoformat(),
        "window_to": date.today().isoformat(),
        "imagery": False,
        "weather": True,
    }
    async with _platform_client() as client:
        first = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert first.status_code == 201, first.text
        again = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert again.status_code == 409, again.text
