"""Forward and reverse lineage.

The overview's consumer count is a time proxy and says so. These endpoints are
the exact answer, and they can be exact because the decision engine already
records what each condition read in `evaluation_snapshot.values`, keyed
`indices.<code>.<field>`.

The reverse direction is the more interesting one: the snapshot froze the
value at decision time while the aggregate row is an upsert, so comparing them
shows when a recommendation is standing on a number that was recomputed
underneath it.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import PlatformRole

from .conftest import WINDOW_FROM, WINDOW_TO, Scenario, build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/observer"

DECIDED_AT = WINDOW_FROM + timedelta(days=5)


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _window() -> dict[str, str]:
    return {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()}


async def _seed_decisions(
    session: AsyncSession, scenario: Scenario, *, observed_ndmi: str
) -> tuple[UUID, UUID]:
    """One recommendation and one alert that read NDMI, plus a distractor.

    The distractor read a different index entirely. If it shows up in the
    NDMI lineage, the match is by timestamp rather than by what was read —
    which is the whole distinction this endpoint exists to make.
    """
    await session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))

    tree_id = uuid4()
    rec_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO recommendations (
                id, block_id, farm_id, tree_id, tree_code, tree_version,
                action_type, severity, confidence, parameters, actions,
                tree_path, text_en, evaluation_snapshot, created_at
            ) VALUES (
                CAST(:rid AS uuid), CAST(:bid AS uuid), CAST(:fid AS uuid),
                CAST(:tid AS uuid), 'mango_water_stress', 4,
                'irrigate', 'warning', 0.9, '{}'::jsonb, '{}'::jsonb,
                '[]'::jsonb, 'increase irrigation', CAST(:snap AS jsonb), :at
            )
            """
        ),
        {
            "rid": str(rec_id),
            "bid": str(scenario.block_a),
            "fid": str(scenario.farm_id),
            "tid": str(tree_id),
            "snap": json.dumps(
                {"tree_match": True, "values": {"indices.ndmi.mean": observed_ndmi}}
            ),
            "at": DECIDED_AT,
        },
    )

    alert_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO alerts (
                id, block_id, rule_code, severity, status,
                signal_snapshot, created_at
            ) VALUES (
                CAST(:aid AS uuid), CAST(:bid AS uuid), 'ndmi_low', 'warning',
                'open', CAST(:snap AS jsonb), :at
            )
            """
        ),
        {
            "aid": str(alert_id),
            "bid": str(scenario.block_a),
            "snap": json.dumps({"values": {"indices.ndmi.mean": observed_ndmi}}),
            "at": DECIDED_AT,
        },
    )

    # Distractor: same block, same window, read NDVI instead.
    await session.execute(
        text(
            """
            INSERT INTO recommendations (
                block_id, farm_id, tree_id, tree_code, tree_version,
                action_type, severity, confidence, parameters, actions,
                tree_path, text_en, evaluation_snapshot, created_at
            ) VALUES (
                CAST(:bid AS uuid), CAST(:fid AS uuid), CAST(:tid AS uuid),
                'ndvi_only_tree', 1, 'scout', 'info', 0.9, '{}'::jsonb, '{}'::jsonb,
                '[]'::jsonb, 'scout the block', CAST(:snap AS jsonb), :at
            )
            """
        ),
        {
            "bid": str(scenario.block_a),
            "fid": str(scenario.farm_id),
            "tid": str(uuid4()),
            "snap": json.dumps({"values": {"indices.ndvi.mean": "0.51"}}),
            "at": DECIDED_AT,
        },
    )
    await session.commit()
    await session.execute(text("SET search_path TO public"))
    return rec_id, alert_id


# ---- forward ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_lineage_lists_only_consumers_that_read_the_index(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The distinction from a timestamp proxy.

    Three decisions on the same block in the same window; two read NDMI and
    one read NDVI. A time-based match would return all three.
    """
    await _seed_decisions(admin_session, scenario, observed_ndmi="0.2871")
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/lineage",
            params={
                "block_id": str(scenario.block_a),
                "index_code": "ndmi",
                **_window(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["exact"] is True
        assert len(body["recommendations"]) == 1
        assert len(body["alerts"]) == 1
        assert body["recommendations"][0]["tree_code"] == "mango_water_stress"
        assert body["alerts"][0]["rule_code"] == "ndmi_low"


@pytest.mark.asyncio
async def test_lineage_returns_the_value_the_tree_actually_saw(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """ "Fired on NDMI = 0.2871" is a finding; "fired the same afternoon" is not."""
    await _seed_decisions(admin_session, scenario, observed_ndmi="0.2871")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage",
                params={
                    "block_id": str(scenario.block_a),
                    "index_code": "ndmi",
                    **_window(),
                },
            )
        ).json()
        rec = body["recommendations"][0]
        assert rec["observed_value"] == "0.2871"
        # Which namespace matched — block-level vs per-cell is a real
        # difference in what the decision was about.
        assert rec["snapshot_key"] == "indices.ndmi.mean"


@pytest.mark.asyncio
async def test_an_index_with_no_consumers_is_empty_not_an_error(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    await _seed_decisions(admin_session, scenario, observed_ndmi="0.2871")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage",
                params={
                    "block_id": str(scenario.block_a),
                    "index_code": "gndvi",
                    **_window(),
                },
            )
        ).json()
        assert body["recommendations"] == []
        assert body["alerts"] == []
        assert body["consumer_count"] == 0


@pytest.mark.asyncio
async def test_cell_anomalies_are_only_computed_when_a_scene_is_named(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The anomaly pass needs a specific scene; without one it is skipped
    rather than guessed at."""
    await _seed_decisions(admin_session, scenario, observed_ndmi="0.2871")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage",
                params={
                    "block_id": str(scenario.block_a),
                    "index_code": "ndmi",
                    **_window(),
                },
            )
        ).json()
        assert body["cell_anomalies"] == []
        assert body["anomaly_threshold"] is None
        assert body["anomaly_threshold_source"] is None


@pytest.mark.asyncio
async def test_naming_a_scene_runs_the_anomaly_pass(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The scenario's cells all share one mean, so a uniform field yields no
    outliers — which is the detector's own answer, not a special case here."""
    await _seed_decisions(admin_session, scenario, observed_ndmi="0.2871")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage",
                params={
                    "block_id": str(scenario.block_a),
                    "index_code": "ndmi",
                    "product": str(scenario.product_id),
                    "scene_time": WINDOW_FROM.isoformat(),
                    **_window(),
                },
            )
        ).json()
        assert body["cell_anomalies"] == []
        # The threshold is reported with its source, so `module_default` is
        # never mistaken for the sweep's tenant-resolved number.
        assert body["anomaly_threshold"] is not None
        assert body["anomaly_threshold_source"] == "module_default"


# ---- reverse ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_lineage_agrees_when_nothing_was_recomputed(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The scenario's NDMI aggregate is 0.5123, so a snapshot recording that
    same value should reconcile."""
    rec_id, _ = await _seed_decisions(admin_session, scenario, observed_ndmi="0.5123")
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/lineage/source",
            params={
                "kind": "recommendation",
                "decision_id": str(rec_id),
                "index_code": "ndmi",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["observed_value"] == pytest.approx(0.5123)
        assert body["current_value"] == pytest.approx(0.5123)
        assert body["values_agree"] is True
        assert body["source_row"] is not None


@pytest.mark.asyncio
async def test_reverse_lineage_shows_a_row_recomputed_after_the_decision(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The finding no other surface can produce.

    The snapshot froze 0.6031; the aggregate now holds 0.5123. The
    recommendation is standing on a number that no longer exists.
    """
    rec_id, _ = await _seed_decisions(admin_session, scenario, observed_ndmi="0.6031")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage/source",
                params={
                    "kind": "recommendation",
                    "decision_id": str(rec_id),
                    "index_code": "ndmi",
                },
            )
        ).json()
        assert body["observed_value"] == pytest.approx(0.6031)
        assert body["current_value"] == pytest.approx(0.5123)
        assert body["values_agree"] is False


@pytest.mark.asyncio
async def test_reverse_lineage_works_for_an_alert_too(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    _, alert_id = await _seed_decisions(admin_session, scenario, observed_ndmi="0.5123")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage/source",
                params={
                    "kind": "alert",
                    "decision_id": str(alert_id),
                    "index_code": "ndmi",
                },
            )
        ).json()
        assert body["source_code"] == "ndmi_low"
        assert body["values_agree"] is True


@pytest.mark.asyncio
async def test_a_decision_that_never_read_the_index_cannot_tell(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """`values_agree` is null, not false.

    "Cannot tell" and "disagrees" are different answers, and collapsing them
    would manufacture a defect out of an unrelated question.
    """
    rec_id, _ = await _seed_decisions(admin_session, scenario, observed_ndmi="0.5123")
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/lineage/source",
                params={
                    "kind": "recommendation",
                    "decision_id": str(rec_id),
                    "index_code": "evi",
                },
            )
        ).json()
        assert body["observed_value"] is None
        assert body["values_agree"] is None


@pytest.mark.asyncio
async def test_an_unknown_decision_is_404(scenario: Scenario) -> None:
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/lineage/source",
            params={
                "kind": "recommendation",
                "decision_id": str(uuid4()),
                "index_code": "ndmi",
            },
        )
        assert r.status_code == 404
