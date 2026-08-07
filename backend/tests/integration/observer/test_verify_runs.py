"""Verification runs: the lifecycle, not the maths.

The recomputation itself is covered by unit tests; what needs a database is
everything that makes a long-running operator action safe — one run per farm,
a cancel that works, a report you can filter, and an audit trail for the one
part of Observer that spends worker time.

Celery dispatch is stubbed. These assert the API and the run rows, not that a
worker picks the job up.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import WINDOW_FROM, WINDOW_TO, Scenario, build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/observer"


@pytest.fixture(autouse=True)
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture dispatched tasks instead of queueing them."""
    sent: list[dict[str, Any]] = []

    def _fake_send_task(name: str, **kwargs: Any) -> None:
        sent.append({"name": name, **kwargs})

    from app.modules.observer import router as observer_router

    monkeypatch.setattr(observer_router.celery_current_app, "send_task", _fake_send_task)
    return sent


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _tenant_client(tenant_id: UUID) -> AsyncClient:
    context = make_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        tenant_role=TenantRole.TENANT_OWNER,
        platform_role=None,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _payload(scenario: Scenario, **overrides: Any) -> dict[str, Any]:
    body = {
        "farm_id": str(scenario.farm_id),
        "window_from": WINDOW_FROM.isoformat(),
        "window_to": WINDOW_TO.isoformat(),
        "mode": "full",
    }
    body.update(overrides)
    return body


# ---- access control --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_tenant_role_cannot_start_a_verification(scenario: Scenario) -> None:
    """Verify spends worker time; no tenant role may trigger it."""
    async with _tenant_client(scenario.tenant_id) as client:
        r = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )
        assert r.status_code == 403


# ---- run lifecycle ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_is_queued_and_dispatched_once(
    scenario: Scenario, sent_tasks: list[dict[str, Any]]
) -> None:
    async with _platform_client() as client:
        r = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )
        assert r.status_code == 201, r.text
        run = r.json()
        assert run["status"] == "queued"
        assert run["mode"] == "full"
        assert run["progress"] == {}

        assert [t["name"] for t in sent_tasks] == ["observer.run_verification"]
        assert sent_tasks[0]["kwargs"]["run_id"] == run["id"]


@pytest.mark.asyncio
async def test_one_run_per_farm_is_enforced(
    scenario: Scenario, sent_tasks: list[dict[str, Any]]
) -> None:
    """A second run would re-read the same COGs while the first is working.

    The 409 names the run holding the farm, so the operator can go cancel it
    rather than guessing.
    """
    async with _platform_client() as client:
        first = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )
        assert first.status_code == 201
        again = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )
        assert again.status_code == 409, again.text
        assert first.json()["id"] in again.text
        # And the refused submit dispatched nothing.
        assert len(sent_tasks) == 1


@pytest.mark.asyncio
async def test_cancelling_frees_the_farm_for_a_new_run(scenario: Scenario) -> None:
    """#332: a run that never settles holds its farm indefinitely.

    Cancel ships with the feature for exactly that reason, and the proof it
    works is that the farm accepts a new run afterwards.
    """
    async with _platform_client() as client:
        run = (
            await client.post(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
            )
        ).json()

        cancelled = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}:cancel"
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["completed_at"] is not None

        second = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )
        assert second.status_code == 201, second.text


@pytest.mark.asyncio
async def test_cancelling_a_finished_run_is_409_and_an_unknown_one_is_404(
    scenario: Scenario,
) -> None:
    """Retrying helps in neither case, but they mean different things."""
    async with _platform_client() as client:
        run = (
            await client.post(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
            )
        ).json()
        await client.post(f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}:cancel")

        again = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}:cancel"
        )
        assert again.status_code == 409

        missing = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{uuid4()}:cancel"
        )
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_a_backwards_window_is_refused(scenario: Scenario) -> None:
    async with _platform_client() as client:
        r = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs",
            json=_payload(
                scenario,
                window_from=WINDOW_TO.isoformat(),
                window_to=WINDOW_FROM.isoformat(),
            ),
        )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_a_window_past_the_cap_is_refused(scenario: Scenario) -> None:
    async with _platform_client() as client:
        r = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs",
            json=_payload(
                scenario,
                window_from=(WINDOW_FROM - timedelta(days=4000)).isoformat(),
                window_to=WINDOW_TO.isoformat(),
            ),
        )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_runs_are_listed_and_fetchable(scenario: Scenario) -> None:
    async with _platform_client() as client:
        run = (
            await client.post(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
            )
        ).json()

        listed = (await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs")).json()
        assert any(r["id"] == run["id"] for r in listed)

        detail = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}")
        assert detail.status_code == 200
        assert detail.json()["farm_id"] == str(scenario.farm_id)

        assert (
            await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{uuid4()}")
        ).status_code == 404


# ---- the report ------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_are_filterable_to_the_drift(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """A finished run is a browsable report, and "show me the drift" is the
    only question anyone asks of a 2,500-scene run."""
    async with _platform_client() as client:
        run = (
            await client.post(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
            )
        ).json()

        await admin_session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))
        for verdict in ("match", "match", "drift"):
            await admin_session.execute(
                text(
                    """
                    INSERT INTO observer_verifications (
                        run_id, block_id, product_id, scene_time, scene_id,
                        mode, verdict, per_index
                    ) VALUES (
                        CAST(:rid AS uuid), CAST(:bid AS uuid), CAST(:pid AS uuid),
                        :st, :scene, 'full', :verdict, '{}'::jsonb
                    )
                    """
                ),
                {
                    "rid": run["id"],
                    "bid": str(scenario.block_a),
                    "pid": str(scenario.product_id),
                    "st": WINDOW_FROM,
                    "scene": f"S2A_{verdict}",
                    "verdict": verdict,
                },
            )
        await admin_session.commit()
        await admin_session.execute(text("SET search_path TO public"))

        all_rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}/results"
            )
        ).json()
        assert len(all_rows) == 3

        drift = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs/{run['id']}/results",
                params={"verdict": "drift"},
            )
        ).json()
        assert len(drift) == 1
        assert drift[0]["verdict"] == "drift"
        # The mode travels with the verdict: a `fast` match means less than a
        # `full` one, and the reader must be able to tell.
        assert drift[0]["mode"] == "full"


@pytest.mark.asyncio
async def test_verifying_a_scene_with_no_raster_is_409(scenario: Scenario) -> None:
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "status": ["failed"],
                    "from": WINDOW_FROM.isoformat(),
                    "to": WINDOW_TO.isoformat(),
                },
            )
        ).json()
        r = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{rows[0]['job_id']}:verify"
        )
        assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_verify_never_writes_to_the_pipeline_tables(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The guarantee the whole feature rests on.

    Observer reports; the Backfill Console repairs. A verify that silently
    corrected an aggregate would destroy the evidence of the defect it found.
    """
    await admin_session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))
    before = (
        await admin_session.execute(
            text("SELECT count(*), max(inserted_at) FROM block_index_aggregates")
        )
    ).one()
    await admin_session.execute(text("SET search_path TO public"))

    async with _platform_client() as client:
        await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/verify-runs", json=_payload(scenario)
        )

    await admin_session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))
    after = (
        await admin_session.execute(
            text("SELECT count(*), max(inserted_at) FROM block_index_aggregates")
        )
    ).one()
    await admin_session.execute(text("SET search_path TO public"))
    assert before == after
