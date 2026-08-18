"""Integration tests for the platform backfill console (/admin/backfill…).

Covers the three things that actually matter for this surface:

  * it is PlatformAdmin-only — a tenant user must not reach it at all;
  * one run per farm is enforced, so a second submit gets a clean 409
    rather than silently burning processing units on duplicate work;
  * a run is persisted with its sources and window so the console has
    something to render (the whole reason the table exists — the Celery
    tasks are ``ignore_result=True`` and store nothing themselves).

Celery dispatch is stubbed: these tests assert the API and the run row,
not that a worker picks the job up.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.shared.auth.context import PlatformRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture dispatched tasks instead of queueing them."""
    sent: list[dict[str, Any]] = []

    def _fake_send_task(name: str, **kwargs: Any) -> None:
        sent.append({"name": name, **kwargs})

    from app.modules.backfill import service as svc

    monkeypatch.setattr(svc.celery_current_app, "send_task", _fake_send_task)
    return sent


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(),
        tenant_id=None,
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _tenant_client(tenant_id: UUID) -> AsyncClient:
    """A plain tenant user — holds no platform capability."""
    context = make_context(user_id=uuid4(), tenant_id=tenant_id, platform_role=None)
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _first_tenant_and_farm(client: AsyncClient) -> tuple[str, str] | None:
    """Find a tenant + farm this console can actually run against.

    "Unoccupied" is necessary but not sufficient: a run also requires the farm
    to have active imagery or weather subscriptions, and `FarmOption` says
    nothing about those. Picking on `active_run_id` alone means any farm that
    some *other* test module seeded — for its own purposes, with no
    subscriptions — can be chosen here, and the run then 422s with a message
    about subscriptions that reads like a backfill bug.

    So the precondition is verified the only way the API exposes it: ask for
    an estimate and keep looking unless it reports a subscription to fetch from.
    """
    probe_from = (date.today() - timedelta(days=30)).isoformat()
    probe_to = date.today().isoformat()
    tenants = (await client.get("/api/v1/admin/backfill/tenants")).json()
    for t in tenants:
        farms = (await client.get(f"/api/v1/admin/backfill/tenants/{t['id']}/farms")).json()
        for farm in farms:
            if farm.get("active_run_id"):
                continue
            est = await client.post(
                f"/api/v1/admin/backfill/tenants/{t['id']}:estimate",
                json={
                    "farm_id": farm["id"],
                    "window_from": probe_from,
                    "window_to": probe_to,
                    "imagery": True,
                    "weather": True,
                },
            )
            if est.status_code != 200:
                continue
            body = est.json()
            # `subscriptions` / `weather_subscriptions` ARE the run's
            # precondition — the estimate exposes them precisely so the console
            # can warn before submitting. A 200 alone proves nothing: estimate
            # happily costs a farm that has nothing to fetch.
            # BOTH, not either: every caller below submits `imagery` AND
            # `weather`, and the run is refused unless the farm has each. With
            # `or` this held only by luck — no module had yet seeded a farm
            # configured for one source — and the first one that did turned
            # these tests red for a reason nowhere near the code under test.
            if body["subscriptions"] > 0 and body["weather_subscriptions"] > 0:
                return t["id"], farm["id"]
    return None


@pytest.mark.asyncio
async def test_tenant_user_cannot_reach_the_console() -> None:
    """The whole surface is platform-only — quota is shared across tenants."""
    async with _tenant_client(uuid4()) as client:
        for path in (
            "/api/v1/admin/backfill/tenants",
            "/api/v1/admin/backfill/runs",
        ):
            r = await client.get(path)
            assert r.status_code == 403, f"{path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_run_lifecycle_and_single_run_per_farm(
    sent_tasks: list[dict[str, Any]],
) -> None:
    async with _platform_client() as client:
        picked = await _first_tenant_and_farm(client)
        if picked is None:
            pytest.skip("no tenant with an unoccupied farm in this fixture DB")
        tenant_id, farm_id = picked

        window_from = date.today() - timedelta(days=30)
        window_to = date.today()
        body = {
            "farm_id": farm_id,
            "window_from": window_from.isoformat(),
            "window_to": window_to.isoformat(),
            "imagery": True,
            "weather": True,
        }

        # Estimate must not create anything.
        est = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}:estimate", json=body)
        assert est.status_code == 200, est.text
        assert est.json()["days"] == 31
        # Never claim a real quota reading — there is no CDSE metering.
        assert est.json()["units_estimated"] is True

        created = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert created.status_code == 201, created.text
        run = created.json()
        assert run["status"] == "queued"
        # Asserted per source rather than as a whole dict. #483 added `thermal`
        # as a third source and this assertion was not updated with it; the
        # test only skips past that when the fixture DB happens to give it no
        # unoccupied farm, so it was green by luck of module ordering. What the
        # request asked for is what must come back — a source it did not
        # mention is not this test's business.
        assert run["sources"]["imagery"] is True
        assert run["sources"]["weather"] is True
        assert run["kind"] == "backfill"

        # Both sources dispatched, and imagery must stay raw-only.
        names = {s["name"] for s in sent_tasks}
        assert "imagery.backfill_farm_scenes" in names
        assert "weather.backfill_weather" in names
        imagery_call = next(s for s in sent_tasks if s["name"].startswith("imagery"))
        assert imagery_call["kwargs"]["run_compute_indices"] is False
        assert imagery_call["kwargs"]["run_id"] == run["id"]

        # Second submit for the same farm is refused, not queued.
        again = await client.post(f"/api/v1/admin/backfill/tenants/{tenant_id}/runs", json=body)
        assert again.status_code == 409, again.text

        # The farm now reports itself occupied so the UI can disable it.
        farms = (await client.get(f"/api/v1/admin/backfill/tenants/{tenant_id}/farms")).json()
        this_farm = next(f for f in farms if f["id"] == farm_id)
        assert this_farm["active_run_id"] == run["id"]

        # And it shows up in the cross-tenant list + detail.
        listed = (await client.get("/api/v1/admin/backfill/runs")).json()
        assert any(r["id"] == run["id"] for r in listed)
        detail = await client.get(f"/api/v1/admin/backfill/runs/{run['id']}")
        assert detail.status_code == 200
        assert detail.json()["farm_id"] == farm_id


@pytest.mark.asyncio
async def test_rejects_a_run_with_no_source_selected() -> None:
    async with _platform_client() as client:
        picked = await _first_tenant_and_farm(client)
        if picked is None:
            pytest.skip("no tenant with an unoccupied farm in this fixture DB")
        tenant_id, farm_id = picked
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{tenant_id}/runs",
            json={
                "farm_id": farm_id,
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": False,
                "weather": False,
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_indices_run_dispatches_the_free_tasks(
    sent_tasks: list[dict[str, Any]],
) -> None:
    """Index computation must never touch the provider."""
    async with _platform_client() as client:
        picked = await _first_tenant_and_farm(client)
        if picked is None:
            pytest.skip("no tenant with an unoccupied farm in this fixture DB")
        tenant_id, farm_id = picked
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{tenant_id}/runs",
            json={
                "farm_id": farm_id,
                "window_from": (date.today() - timedelta(days=7)).isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": True,
                "weather": True,
                "kind": "indices",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "indices"
        names = {s["name"] for s in sent_tasks}
        assert names == {
            "imagery.backfill_farm_indices",
            "weather.backfill_weather_indices",
        }


@pytest.mark.asyncio
async def test_rejects_a_source_the_farm_has_no_subscriptions_for(
    sent_tasks: list[dict[str, Any]],
) -> None:
    """A farm with no active subscriptions must be refused, not silently no-op.

    Both providers are driven entirely by the farm's per-block
    subscriptions, so dispatching for an unconfigured source would fetch
    nothing and report success -- the worst outcome for an operator who
    believes they just loaded a year of history.
    """
    async with _platform_client() as client:
        tenants = (await client.get("/api/v1/admin/backfill/tenants")).json()
        target: tuple[str, str] | None = None
        for t in tenants:
            farms = (await client.get(f"/api/v1/admin/backfill/tenants/{t['id']}/farms")).json()
            for f in farms:
                if f.get("active_run_id"):
                    continue
                est = await client.post(
                    f"/api/v1/admin/backfill/tenants/{t['id']}:estimate",
                    json={
                        "farm_id": f["id"],
                        "window_from": date.today().isoformat(),
                        "window_to": date.today().isoformat(),
                        "imagery": True,
                        "weather": True,
                    },
                )
                if est.status_code == 200 and est.json()["subscriptions"] == 0:
                    target = (t["id"], f["id"])
                    break
            if target:
                break
        if target is None:
            pytest.skip("every farm in this fixture DB has imagery subscriptions")

        tenant_id, farm_id = target
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{tenant_id}/runs",
            json={
                "farm_id": farm_id,
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": True,
                "weather": False,
            },
        )
        assert r.status_code == 422, r.text
        assert "imagery" in r.text
        # Plain sentence, not a stringified dict -- the operator reads this.
        assert "{" not in r.json()["detail"]
        # Nothing may be queued for a rejected run.
        assert sent_tasks == []


@pytest.mark.asyncio
async def test_estimate_reports_the_farms_weather_integration() -> None:
    """The estimate must expose what the farm is actually wired up for."""
    async with _platform_client() as client:
        picked = await _first_tenant_and_farm(client)
        if picked is None:
            pytest.skip("no tenant with an unoccupied farm in this fixture DB")
        tenant_id, farm_id = picked
        r = await client.post(
            f"/api/v1/admin/backfill/tenants/{tenant_id}:estimate",
            json={
                "farm_id": farm_id,
                "window_from": date.today().isoformat(),
                "window_to": date.today().isoformat(),
                "imagery": True,
                "weather": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "weather_subscriptions" in body
        assert isinstance(body["weather_providers"], list)
        # Providers must be real subscription codes, never a guessed literal:
        # the worker's _make_provider raises on anything unrecognised.
        for code in body["weather_providers"]:
            assert code != "open-meteo", "hyphenated code would fail _make_provider"
