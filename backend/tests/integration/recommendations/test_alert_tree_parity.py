"""Alert parity test for the trees-as-alerts sunset (PR-F).

The `ndvi_baseline_alert_v1` seed YAML replaces two `default_rules`
rows (`ndvi_severe_drop` + `ndvi_warning_drop`). This test proves that
the new tree, walking via the recommendations engine, opens a row in
`tenant.alerts` for the same NDVI baseline-deviation signal the old
rules used to fire on — same partial-UNIQUE-key idempotency, same
notifications fan-out (covered separately under
`tests/integration/notifications/`).

Two scenarios:

  1. NDVI baseline_deviation = -2.0 → crosses both thresholds; the
     tree walks to the `leaf_alert_critical` leaf and writes a
     critical alert.
  2. NDVI baseline_deviation = -1.0 → between warning and critical;
     tree walks to `leaf_alert_warning` and writes a warning alert.

The third (no-drop) scenario doesn't need its own test — the
existing recommendations test suite already covers "no outcome →
no row written".
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.loader import sync_from_disk
from app.modules.recommendations.service import get_recommendations_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


async def _ensure_seed_trees_loaded(admin_session: AsyncSession) -> None:
    """Tests skip app-startup lifespan so the seed YAMLs aren't synced
    into `public.decision_trees`. Call `sync_from_disk` ourselves so the
    `ndvi_baseline_alert_v1` tree is present for the sweep to pick up.
    Idempotent: re-running with no YAML changes is a no-op."""
    await sync_from_disk(admin_session)


async def _seed_block_with_ndvi(
    admin_session: AsyncSession, schema_name: str, *, deviation: Decimal
) -> tuple[UUID, UUID]:
    farm_id = uuid4()
    block_id = uuid4()
    product_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, 'PRF-FARM', 'PR-F Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type) "
            "VALUES (:bid, :fid, 'B-PRF', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'prf-aoi', 'block')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_index_aggregates ("
            "  time, block_id, index_code, product_id, mean, "
            "  valid_pixel_count, total_pixel_count, stac_item_id, baseline_deviation"
            ") VALUES ("
            "  :time, :block_id, 'ndvi', :product_id, 0.45, "
            "  100, 100, 'prf/scene', :deviation"
            ")"
        ).bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("product_id", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "time": datetime.now(UTC).replace(microsecond=0),
            "block_id": block_id,
            "product_id": product_id,
            "deviation": deviation,
        },
    )
    await admin_session.commit()
    return farm_id, block_id


async def _run_recommendations_sweep_one_block(
    schema_name: str, tenant_id: UUID, block_id: UUID
) -> None:
    """Evaluate every tree visible to the tenant against one block.
    Mirrors the production sweep but for a single block so the test
    stays focused. Tree-sourced alert leaves land in tenant.alerts
    via `_open_alert_from_tree` (PR-E)."""
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(
                tenant_session=session, public_session=public_session
            )
            await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=schema_name,
                tenant_id=tenant_id,
            )


@pytest.mark.asyncio
async def test_severe_ndvi_drop_opens_critical_alert_via_tree(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    await _ensure_seed_trees_loaded(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prf-critical-{uuid4().hex[:6]}",
        name="PR-F Critical",
        contact_email="ops@prf-critical.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    await _run_recommendations_sweep_one_block(
        tenant.schema_name, tenant.tenant_id, block_id
    )

    # Tree-sourced alert lands in tenant.alerts with a synthesised
    # rule_code per PR-E's convention.
    rows = (
        await admin_session.execute(
            text(
                f'SELECT rule_code, severity, status FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid ORDER BY created_at DESC"
            ),
            {"bid": block_id},
        )
    ).mappings().all()
    assert len(rows) >= 1, "expected the tree to open one alert for the block"
    critical = next(
        (
            r
            for r in rows
            if r["rule_code"].startswith("tree:ndvi_baseline_alert_v1:")
        ),
        None,
    )
    assert critical is not None, f"no tree-sourced alert; got: {[dict(r) for r in rows]}"
    assert critical["severity"] == "critical"
    assert critical["status"] == "open"
    assert critical["rule_code"].endswith(":leaf_alert_critical")


@pytest.mark.asyncio
async def test_moderate_ndvi_drop_opens_warning_alert_via_tree(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    await _ensure_seed_trees_loaded(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prf-warning-{uuid4().hex[:6]}",
        name="PR-F Warning",
        contact_email="ops@prf-warning.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi(
        admin_session, tenant.schema_name, deviation=Decimal("-1.0")
    )

    await _run_recommendations_sweep_one_block(
        tenant.schema_name, tenant.tenant_id, block_id
    )

    rows = (
        await admin_session.execute(
            text(
                f'SELECT rule_code, severity FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid ORDER BY created_at DESC"
            ),
            {"bid": block_id},
        )
    ).mappings().all()
    warning = next(
        (
            r
            for r in rows
            if r["rule_code"].endswith(":leaf_alert_warning")
        ),
        None,
    )
    assert warning is not None, f"no warning alert; got: {[dict(r) for r in rows]}"
    assert warning["severity"] == "warning"


@pytest.mark.asyncio
async def test_tenant_param_override_changes_threshold(
    admin_session: AsyncSession,
) -> None:
    """PR-C parameter override replaces the old `rule_overrides`
    threshold-tweak workflow. A tenant who tightens the critical
    threshold gets a critical alert for a deviation the default
    threshold would have flagged as warning."""
    tenancy = get_tenant_service(admin_session)
    await _ensure_seed_trees_loaded(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prf-override-{uuid4().hex[:6]}",
        name="PR-F Override",
        contact_email="ops@prf-override.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi(
        admin_session, tenant.schema_name, deviation=Decimal("-1.0")
    )

    # Tighten critical_threshold so -1.0 is now `critical` instead of
    # `warning`. Looks up the platform tree's id directly to avoid
    # needing the authoring service for a read.
    row = (
        await admin_session.execute(
            text(
                "SELECT id FROM public.decision_trees "
                "WHERE code = 'ndvi_baseline_alert_v1' AND tenant_id IS NULL"
            )
        )
    ).first()
    assert row is not None, "ndvi_baseline_alert_v1 seed not loaded"
    tree_id = row.id
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant.schema_name}".tree_parameter_overrides '
            "(tree_id, param_name, value) VALUES (:tid, :n, CAST(:v AS jsonb))"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tree_id, "n": "critical_threshold", "v": "-0.5"},
    )
    await admin_session.commit()

    await _run_recommendations_sweep_one_block(
        tenant.schema_name, tenant.tenant_id, block_id
    )

    rows = (
        await admin_session.execute(
            text(
                f'SELECT rule_code, severity FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid"
            ),
            {"bid": block_id},
        )
    ).mappings().all()
    critical = next(
        (r for r in rows if r["rule_code"].endswith(":leaf_alert_critical")), None
    )
    assert critical is not None, (
        f"override should have triggered a critical alert; got: {[dict(r) for r in rows]}"
    )
    assert critical["severity"] == "critical"
