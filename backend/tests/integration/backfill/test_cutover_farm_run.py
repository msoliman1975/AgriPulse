"""Submitting a backfill for a farm that fetches its whole AOI.

The console's pre-flight is the operator's only view of what a run will
cost, and its guard is the only thing standing between them and a run that
fetches nothing. Both were written when every farm was fetched per block:

  * the guard asked only about block subscriptions, so a farm far enough
    through the cutover to have had its block rows deactivated was refused
    with "no active imagery subscriptions" — on exactly the farms where the
    whole-farm fetch works best;
  * the estimate counted those same block rows, so a cut-over farm was
    quoted N fetches per pass when the run now makes one.

Celery dispatch is stubbed; the database is real.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

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
async def seeded(admin_session: Any) -> dict[str, Any]:
    """A tenant with one farm, one block, and an active block imagery sub."""
    slug = f"bfx-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'BFX', 'BFX farm', "
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
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {
        "tenant_id": tenant.tenant_id,
        "farm_id": farm_id,
        "product_id": product_id,
        "schema": schema,
    }


async def _cut_over(
    admin_session: Any,
    seeded: dict[str, Any],
    *,
    fetch_farm_aoi: bool = True,
    deactivate_blocks: bool = False,
) -> None:
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions "
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, :fetch)"
        ),
        {
            "id": str(uuid4()),
            "farm": str(seeded["farm_id"]),
            "product": str(seeded["product_id"]),
            "fetch": fetch_farm_aoi,
        },
    )
    if deactivate_blocks:
        await admin_session.execute(text("UPDATE imagery_aoi_subscriptions SET is_active = FALSE"))
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()


async def _estimate(client: AsyncClient, seeded: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}:estimate",
        json={
            "farm_id": str(seeded["farm_id"]),
            "window_from": (date.today() - timedelta(days=9)).isoformat(),
            "window_to": date.today().isoformat(),
            "imagery": True,
            "weather": False,
        },
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


@pytest.mark.asyncio
async def test_a_plain_farm_is_still_quoted_per_block(seeded: dict[str, Any]) -> None:
    async with _platform_client() as client:
        est = await _estimate(client, seeded)
    assert est["subscriptions"] == 1
    assert est["farm_aoi_subscriptions"] == 0


@pytest.mark.asyncio
async def test_a_dormant_farm_row_does_not_change_the_quote(
    admin_session: Any, seeded: dict[str, Any]
) -> None:
    """0074 gave every farm one of these. It must count for nothing."""
    await _cut_over(admin_session, seeded, fetch_farm_aoi=False)
    async with _platform_client() as client:
        est = await _estimate(client, seeded)
    assert est["subscriptions"] == 1
    assert est["farm_aoi_subscriptions"] == 0


@pytest.mark.asyncio
async def test_a_cut_over_farm_is_quoted_as_one_whole_farm_fetch(
    admin_session: Any, seeded: dict[str, Any]
) -> None:
    await _cut_over(admin_session, seeded)
    async with _platform_client() as client:
        est = await _estimate(client, seeded)
    # The block is covered by the farm fetch, so it is not quoted twice.
    assert est["subscriptions"] == 1
    assert est["farm_aoi_subscriptions"] == 1


@pytest.mark.asyncio
async def test_a_farm_with_only_a_whole_farm_subscription_is_accepted(
    admin_session: Any, seeded: dict[str, Any], sent_tasks: list[dict[str, Any]]
) -> None:
    """The regression: this farm used to be refused as unconfigured."""
    await _cut_over(admin_session, seeded, deactivate_blocks=True)

    async with _platform_client() as client:
        est = await _estimate(client, seeded)
        # Zero here is what makes the console warn "would fetch nothing", so
        # the quote and the guard have to agree about what is fetchable.
        assert est["subscriptions"] == 1
        assert est["farm_aoi_subscriptions"] == 1

        created = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}/runs",
            json={
                "farm_id": str(seeded["farm_id"]),
                "window_from": (date.today() - timedelta(days=9)).isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": True,
                "weather": False,
            },
        )
        assert created.status_code == 201, created.text

    assert {s["name"] for s in sent_tasks} == {"imagery.backfill_farm_scenes"}


@pytest.mark.asyncio
async def test_weather_resolves_from_the_farm_row_when_the_block_rows_are_gone(
    admin_session: Any, seeded: dict[str, Any], sent_tasks: list[dict[str, Any]]
) -> None:
    """Weather was always farm-shaped; 0077 moved the subscription to match.

    The console kept resolving providers from the per-block rows, so a farm
    whose weather lives only on the farm row read as having no weather
    integration — refused with a message telling the operator to configure
    what is already configured.
    """
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO weather_farm_subscriptions (id, farm_id, provider_code, "
            "cadence_hours, is_active) VALUES (:id, :farm, 'open_meteo', 6, TRUE)"
        ),
        {"id": str(uuid4()), "farm": str(seeded["farm_id"])},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    async with _platform_client() as client:
        est = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}:estimate",
            json={
                "farm_id": str(seeded["farm_id"]),
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": False,
                "weather": True,
            },
        )
        assert est.status_code == 200, est.text
        assert est.json()["weather_providers"] == ["open_meteo"]
        assert est.json()["weather_subscriptions"] == 1

        created = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}/runs",
            json={
                "farm_id": str(seeded["farm_id"]),
                "window_from": (date.today() - timedelta(days=2)).isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": False,
                "weather": True,
            },
        )
        assert created.status_code == 201, created.text

    # The provider code must come from the data, never a literal: the worker's
    # `_make_provider` raises on anything it does not recognise.
    assert [s["kwargs"]["provider_code"] for s in sent_tasks] == ["open_meteo"]


@pytest.mark.asyncio
async def test_a_block_weather_row_is_not_counted_twice(
    admin_session: Any, seeded: dict[str, Any]
) -> None:
    """One farm row plus its own block row is still one fetch, not two."""
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    block_id = (await admin_session.execute(text("SELECT id FROM blocks LIMIT 1"))).scalar_one()
    await admin_session.execute(
        text(
            "INSERT INTO weather_subscriptions (block_id, provider_code, cadence_hours, "
            "is_active) VALUES (:bid, 'open_meteo', 6, TRUE)"
        ),
        {"bid": str(block_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO weather_farm_subscriptions (id, farm_id, provider_code, "
            "cadence_hours, is_active) VALUES (:id, :farm, 'open_meteo', 6, TRUE)"
        ),
        {"id": str(uuid4()), "farm": str(seeded["farm_id"])},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    async with _platform_client() as client:
        est = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}:estimate",
            json={
                "farm_id": str(seeded["farm_id"]),
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": False,
                "weather": True,
            },
        )
    assert est.json()["weather_providers"] == ["open_meteo"]
    assert est.json()["weather_subscriptions"] == 1


@pytest.mark.asyncio
async def test_a_farm_with_no_subscriptions_at_all_is_still_refused(
    admin_session: Any, seeded: dict[str, Any]
) -> None:
    """Widening the guard must not turn it off."""
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    await admin_session.execute(text("UPDATE imagery_aoi_subscriptions SET is_active = FALSE"))
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    async with _platform_client() as client:
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{seeded['tenant_id']}/runs",
            json={
                "farm_id": str(seeded["farm_id"]),
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": True,
                "weather": False,
            },
        )
        assert r.status_code == 422, r.text
        assert "imagery" in r.json()["detail"]
