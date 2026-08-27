"""A farm whose grid cells are empty must be reported.

The fix in this release makes the backfill see farm-wide scenes. This
detector is the guard that survives the next variant of the same mistake:
whatever the reason, a farm holding live grid geometry, stored scenes and
no cell readings at all is wrong, and nothing else in the product could
see it. Nothing failed, no job was stuck, no stream was silent — the map
drew the mesh and every cell read "—".

Runs the real statement against a real database. The two production SQL
bugs in this area both survived review because the only tests used a fake
repository.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_alerts.detectors import Thresholds, detect_grid_unbackfilled
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"

TH = Thresholds(
    weather_warn_hours=26,
    weather_crit_hours=50,
    optical_warn_hours=144,
    optical_crit_hours=240,
    thermal_warn_hours=288,
    thermal_crit_hours=480,
    peer_lag_hours=26,
    stuck_job_hours=6,
    streak_threshold=3,
    new_subscription_grace_hours=26,
    grid_backfill_grace_hours=6,
)


async def _env(
    admin_session: AsyncSession,
    *,
    grid_age_hours: int = 48,
    scenes: int = 3,
    farm_path: bool = True,
) -> dict[str, Any]:
    """One gridded farm with scenes and no cell readings.

    ``farm_path`` picks which table the scenes land in. Both are seeded by
    the same helper on purpose: a detector that reads one table and not the
    other is the failure being guarded against, so the test has to be able
    to produce either shape.
    """
    slug = f"gub-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    product_id = UUID(
        str(
            (
                await admin_session.execute(
                    text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
                )
            ).scalar_one()
        )
    )
    farm_id, block_id, sub_id = uuid4(), uuid4(), uuid4()
    created_at = datetime.now(UTC) - timedelta(hours=grid_age_hours)

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'GUB', 'Empty grid farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :farm, 'GB', 'GB', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(block_id), "farm": str(farm_id), "wkt": _BLOCK},
    )
    await admin_session.execute(
        text(
            "INSERT INTO grid_configs "
            "  (id, block_id, product_id, cell_size_m, utm_srid, created_at) "
            "VALUES (:id, :block, :product, 30, 32636, :created)"
        ),
        {
            "id": str(uuid4()),
            "block": str(block_id),
            "product": str(product_id),
            "created": created_at,
        },
    )

    if farm_path:
        await admin_session.execute(
            text(
                "INSERT INTO imagery_farm_subscriptions "
                "  (id, farm_id, product_id, is_active, fetch_farm_aoi) "
                "VALUES (:id, :farm, :product, TRUE, TRUE)"
            ),
            {"id": str(sub_id), "farm": str(farm_id), "product": str(product_id)},
        )
    else:
        await admin_session.execute(
            text(
                "INSERT INTO imagery_aoi_subscriptions "
                "  (id, block_id, product_id, cadence_hours, is_active) "
                "VALUES (:id, :block, :product, 24, true)"
            ),
            {"id": str(sub_id), "block": str(block_id), "product": str(product_id)},
        )

    for i in range(scenes):
        when = datetime.now(UTC) - timedelta(days=i + 1)
        if farm_path:
            await admin_session.execute(
                text(
                    "INSERT INTO imagery_farm_ingestion_jobs "
                    "  (id, subscription_id, farm_id, product_id, scene_id, "
                    "   scene_datetime, status) "
                    "VALUES (:id, :sub, :farm, :product, :scene, :dt, 'succeeded')"
                ),
                {
                    "id": str(uuid4()),
                    "sub": str(sub_id),
                    "farm": str(farm_id),
                    "product": str(product_id),
                    "scene": f"s-{uuid4().hex[:8]}",
                    "dt": when,
                },
            )
        else:
            await admin_session.execute(
                text(
                    "INSERT INTO imagery_ingestion_jobs "
                    "  (id, subscription_id, block_id, product_id, scene_id, "
                    "   scene_datetime, status) "
                    "VALUES (:id, :sub, :block, :product, :scene, :dt, 'succeeded')"
                ),
                {
                    "id": str(uuid4()),
                    "sub": str(sub_id),
                    "block": str(block_id),
                    "product": str(product_id),
                    "scene": f"s-{uuid4().hex[:8]}",
                    "dt": when,
                },
            )

    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_id": block_id,
        "product_id": product_id,
    }


async def _run(admin_session: AsyncSession, env: dict[str, Any]) -> list[Any]:
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    findings = await detect_grid_unbackfilled(admin_session, tenant_key="t", th=TH)
    await admin_session.execute(text("SET search_path TO public"))
    # Other tests build tenants in the same database, and the sweep is
    # per-schema. Scope to this farm rather than asserting a total.
    return [f for f in findings if f.farm_id == env["farm_id"]]


@pytest.mark.asyncio
async def test_a_farm_path_farm_with_empty_cells_is_reported(admin_session: Any) -> None:
    """The production shape, exactly: scenes on the farm path, cells empty."""
    env = await _env(admin_session, farm_path=True, scenes=3)
    found = await _run(admin_session, env)

    assert len(found) == 1, found
    f = found[0]
    assert f.kind == "grid_unbackfilled"
    assert f.category == "index_calc"
    # Warning, not critical. Every block-level number still works; what is
    # missing is the sub-block detail.
    assert f.severity == "warning"
    assert f.context["farm_scenes"] == 3
    assert f.context["block_scenes"] == 0
    # Which path the farm is on decides which repair works, so it has to be
    # in the alert rather than looked up afterwards.
    assert f.context["imagery_path"] == "farm-wide"


@pytest.mark.asyncio
async def test_a_block_path_farm_with_empty_cells_is_reported_too(admin_session: Any) -> None:
    """The detector must not acquire the blindness it exists to catch."""
    env = await _env(admin_session, farm_path=False, scenes=2)
    found = await _run(admin_session, env)

    assert len(found) == 1, found
    assert found[0].context["block_scenes"] == 2
    assert found[0].context["imagery_path"] == "per-block"


@pytest.mark.asyncio
async def test_a_fresh_grid_is_inside_its_grace_period(admin_session: Any) -> None:
    """The apply fires a backfill, and a farm-sized replay takes time.

    Alerting on the minute the grid is created would fire on every healthy
    apply, and an alert that is usually wrong stops being read.
    """
    env = await _env(admin_session, grid_age_hours=1, scenes=3)
    assert await _run(admin_session, env) == []


@pytest.mark.asyncio
async def test_a_farm_with_one_cell_reading_is_not_reported(admin_session: Any) -> None:
    """One reading anywhere means the path works.

    Coverage gaps are a different problem with a different fix, and folding
    them in here would make this alert fire on farms that are merely part
    way through a backfill.
    """
    env = await _env(admin_session, scenes=3)
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    assert (await admin_session.execute(text("SELECT current_schema()"))).scalar_one() == env[
        "schema"
    ]
    cell_id = uuid4()
    config_id = (
        await admin_session.execute(
            text("SELECT id FROM grid_configs WHERE block_id = :b"),
            {"b": str(env["block_id"])},
        )
    ).scalar_one()
    # `geom` is the config's UTM zone; `centroid` is a 4326 column. Same
    # split as the real writer in GridRepository.
    await admin_session.execute(
        text(
            "INSERT INTO grid_cells "
            "  (id, grid_config_id, row_idx, col_idx, geom, centroid, area_m2) "
            "VALUES (:id, :cfg, 0, 0, "
            "        ST_Transform(ST_GeomFromText(:wkt, 4326), 32636), "
            "        ST_Centroid(ST_GeomFromText(:wkt, 4326)), 900)"
        ),
        {"id": str(cell_id), "cfg": str(config_id), "wkt": _BLOCK},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_grid_aggregates "
            "  (time, cell_id, block_id, index_code, product_id, mean) "
            "VALUES (now(), :cell, :block, 'ndvi', :product, 0.42)"
        ),
        {
            "cell": str(cell_id),
            "block": str(env["block_id"]),
            "product": str(env["product_id"]),
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    assert await _run(admin_session, env) == []


@pytest.mark.asyncio
async def test_a_gridded_farm_with_no_scenes_yet_is_not_reported(admin_session: Any) -> None:
    """Empty cells on a farm with no imagery is the correct state.

    A farm gridded before its first pass has nothing to backfill, and
    calling that a fault would put a permanent alert on every new farm.
    """
    env = await _env(admin_session, scenes=0)
    assert await _run(admin_session, env) == []
