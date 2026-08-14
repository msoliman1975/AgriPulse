"""Round-tripping a tenant's inputs into a simulation tenant.

The assertions that matter here are the negative ones. A clone that carries a
customer's farm names into a bucket, or carries their alerts into a run that is
supposed to *produce* alerts, fails in a way nothing downstream would notice:
the first looks like a working seed, the second looks like a working pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.simulation.snapshot import (
    DELIBERATELY_NOT_CLONED,
    SnapshotError,
    extract,
    load,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FID = bindparam("fid", type_=PG_UUID(as_uuid=True))
_BID = bindparam("bid", type_=PG_UUID(as_uuid=True))

_CUSTOMER_FARM_NAME = "Bashayer El Kheir Estate"
_CUSTOMER_BLOCK_CODE = "BEK-MANGO-07"


async def _tenant(session: AsyncSession, prefix: str):
    service = get_tenant_service(session)
    return await service.create_tenant(
        slug=f"{prefix}-{uuid4().hex[:8]}",
        name="Snapshot test",
        contact_email="ops@snap.test",
    )


async def _seed_source(session: AsyncSession, schema: str) -> tuple[UUID, UUID]:
    """A farm, a block, index history, and an alert that must not travel."""
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, 'BEK-01', :name, "
            "'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "'SRID=4326;POINT(31.205 30.105)'::geometry, 100)"
        ).bindparams(_FID),
        {"fid": farm_id, "name": _CUSTOMER_FARM_NAME},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary, boundary_utm, "
            "centroid, area_m2, unit_type) "
            "VALUES (:bid, :fid, :code, 'Mango North', "
            "'SRID=4326;POLYGON((31.2 30.1, 31.205 30.1, 31.205 30.105, 31.2 30.105, 31.2 30.1))'::geometry, "
            "'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "'SRID=4326;POINT(31.2025 30.1025)'::geometry, 50, 'block')"
        ).bindparams(_BID, _FID),
        {"bid": block_id, "fid": farm_id, "code": _CUSTOMER_BLOCK_CODE},
    )
    # A real platform-catalog product id. It must survive the remap
    # untouched, or the clone points at an imagery product that does not exist.
    product_id = (
        await session.execute(text("SELECT id FROM public.imagery_products LIMIT 1"))
    ).scalar_one()
    # Index history: the input a decision tree evaluates against.
    for day in range(5):
        await session.execute(
            text(
                "INSERT INTO block_index_aggregates "
                "(block_id, time, index_code, product_id, stac_item_id, mean, "
                "valid_pixel_count, total_pixel_count) "
                "VALUES (:bid, :t, 'ndvi', :pid, :stac, :v, 100, 100)"
            ).bindparams(_BID, bindparam("pid", type_=PG_UUID(as_uuid=True))),
            {
                "bid": block_id,
                "pid": product_id,
                "stac": f"sim-scene-{day}",
                "t": datetime(2026, 3, 1, tzinfo=UTC) + timedelta(days=day),
                "v": 0.5 + day / 100,
            },
        )
    # An output. It must not travel.
    await session.execute(
        text(
            "INSERT INTO alerts (block_id, rule_code, severity, diagnosis_en, status) "
            "VALUES (:bid, 'tree:x:leaf', 'critical', 'Real customer alert', 'open')"
        ).bindparams(_BID),
        {"bid": block_id},
    )
    await session.commit()
    return farm_id, block_id


@pytest.mark.asyncio
async def test_snapshot_carries_inputs_and_strips_the_customer(
    admin_session: AsyncSession,
) -> None:
    source = await _tenant(admin_session, "snapsrc")
    farm_id, block_id = await _seed_source(admin_session, source.schema_name)

    snapshot = await extract(admin_session, source_schema=source.schema_name)

    farms = snapshot["tables"]["farms"]["rows"]
    blocks = snapshot["tables"]["blocks"]["rows"]
    assert len(farms) == 1
    assert len(blocks) == 1
    assert len(snapshot["tables"]["block_index_aggregates"]["rows"]) == 5

    # Nothing of the customer survives, anywhere in the file.
    serialised = json.dumps(snapshot)
    assert _CUSTOMER_FARM_NAME not in serialised
    assert _CUSTOMER_BLOCK_CODE not in serialised
    assert "Mango North" not in serialised
    assert farms[0]["name"].startswith("SIM-")
    assert blocks[0]["code"].startswith("SIM-")

    # Row identifiers are remapped, so the file cannot be joined back to the
    # customer's tenant and two loads cannot collide in public.farm_scopes.
    assert str(farm_id) not in serialised
    assert str(block_id) not in serialised

    # Geometry survives as EWKT with its SRID, or the clone is worthless.
    assert farms[0]["boundary"].startswith("SRID=4326;")

    # The remap rewrites our own row ids and nothing else. A product id belongs
    # to the platform catalog, is not the primary key of anything cloned, and
    # must come through untouched -- rewriting it would point the clone at an
    # imagery product that does not exist.
    product_id = (
        await admin_session.execute(text("SELECT id FROM public.imagery_products LIMIT 1"))
    ).scalar_one()
    aggregates = snapshot["tables"]["block_index_aggregates"]["rows"]
    assert {r["product_id"] for r in aggregates} == {str(product_id)}

    # Outputs are absent by construction, not by omission.
    assert "alerts" not in snapshot["tables"]
    assert "alerts" in DELIBERATELY_NOT_CLONED


@pytest.mark.asyncio
async def test_load_rebases_history_onto_the_run_date(admin_session: AsyncSession) -> None:
    """The tenant has to be born mid-season, or no tree has anything to read."""
    source = await _tenant(admin_session, "snapsrc")
    await _seed_source(admin_session, source.schema_name)
    target = await _tenant(admin_session, "snaptgt")

    snapshot = await extract(admin_session, source_schema=source.schema_name)
    as_of = datetime(2026, 8, 13, tzinfo=UTC)
    report = await load(
        admin_session, target_schema=target.schema_name, snapshot=snapshot, as_of=as_of
    )
    await admin_session.commit()

    assert report["tables"]["farms"] == 1
    assert report["tables"]["block_index_aggregates"] == 5

    newest = (
        await admin_session.execute(
            text(f'SELECT max(time) FROM "{target.schema_name}".block_index_aggregates')
        )
    ).scalar_one()
    assert newest == as_of - timedelta(days=1)

    # Relative spacing is preserved: five consecutive days stay five days.
    oldest = (
        await admin_session.execute(
            text(f'SELECT min(time) FROM "{target.schema_name}".block_index_aggregates')
        )
    ).scalar_one()
    assert (newest - oldest) == timedelta(days=4)


@pytest.mark.asyncio
async def test_loaded_subscriptions_are_inactive(admin_session: AsyncSession) -> None:
    """Loading a snapshot must never start a real provider fetching."""
    source = await _tenant(admin_session, "snapsrc")
    _, block_id = await _seed_source(admin_session, source.schema_name)
    await admin_session.execute(
        text(
            f'INSERT INTO "{source.schema_name}".weather_subscriptions '
            "(block_id, provider_code, is_active) VALUES (:bid, 'open_meteo', TRUE)"
        ).bindparams(_BID),
        {"bid": block_id},
    )
    await admin_session.commit()
    target = await _tenant(admin_session, "snaptgt")

    snapshot = await extract(admin_session, source_schema=source.schema_name)
    await load(admin_session, target_schema=target.schema_name, snapshot=snapshot)
    await admin_session.commit()

    active = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{target.schema_name}".weather_subscriptions '
                "WHERE is_active"
            )
        )
    ).scalar_one()
    assert active == 0


@pytest.mark.asyncio
async def test_outputs_are_not_carried_into_the_target(admin_session: AsyncSession) -> None:
    """The assertion that keeps Act 3 honest.

    If a cloned alert landed in the target, the harness would assert "alerts
    exist" after triggering evaluation and pass on the clone's rows — reporting
    a working pipeline while the pipeline was dead.
    """
    source = await _tenant(admin_session, "snapsrc")
    await _seed_source(admin_session, source.schema_name)
    target = await _tenant(admin_session, "snaptgt")

    snapshot = await extract(admin_session, source_schema=source.schema_name)
    await load(admin_session, target_schema=target.schema_name, snapshot=snapshot)
    await admin_session.commit()

    for table in ("alerts", "recommendations", "irrigation_schedules"):
        count = (
            await admin_session.execute(
                text(f'SELECT count(*) FROM "{target.schema_name}".{table}')
            )
        ).scalar_one()
        assert count == 0, f"{table} was cloned; Act 3 would assert on stale rows"


@pytest.mark.asyncio
async def test_extract_refuses_a_tenant_with_no_farms(admin_session: AsyncSession) -> None:
    empty = await _tenant(admin_session, "snapempty")
    with pytest.raises(SnapshotError):
        await extract(admin_session, source_schema=empty.schema_name)
