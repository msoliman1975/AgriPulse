"""Tests for the irrigation module — engine pure-functions + integration.

Pure-function half exercises ``compute_recommendation`` against various
ET₀ / precip / Kc combinations. Integration half seeds weather +
crop + block, runs the engine, asserts the schedule lands and that
re-running is idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.irrigation.engine import (
    IrrigationInputs,
    compute_recommendation,
    lookup_kc,
)
from app.modules.irrigation.service import get_irrigation_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Pure-function: lookup_kc
# ---------------------------------------------------------------------------


def test_lookup_kc_falls_back_to_default_when_no_phenology() -> None:
    assert lookup_kc(growth_stage="vegetative", phenology_stages=None) == Decimal("0.70")


def test_lookup_kc_returns_default_for_unknown_stage_with_no_phenology() -> None:
    out = lookup_kc(growth_stage="weird_stage", phenology_stages=None)
    assert out == Decimal("0.85")  # default bucket


def test_lookup_kc_uses_catalog_value_when_present() -> None:
    phenology = {
        "stages": [
            {"code": "flowering", "kc": 1.25, "start_gdd": 600, "end_gdd": 900},
        ]
    }
    out = lookup_kc(growth_stage="flowering", phenology_stages=phenology)
    assert out == Decimal("1.25")


def test_lookup_kc_supports_dict_keyed_phenology_layout() -> None:
    phenology = {"stages": {"vegetative": {"kc": 0.65}}}
    out = lookup_kc(growth_stage="vegetative", phenology_stages=phenology)
    assert out == Decimal("0.65")


# ---------------------------------------------------------------------------
# Pure-function: compute_recommendation
# ---------------------------------------------------------------------------


def _inputs(
    *,
    et0: str = "5.0",
    precip: str = "0.0",
    stage: str = "vegetative",
    eff: str = "0.85",
) -> IrrigationInputs:
    return IrrigationInputs(
        et0_mm_today=Decimal(et0),
        recent_precip_mm=Decimal(precip),
        growth_stage=stage,
        phenology_stages=None,
        application_efficiency=Decimal(eff),
    )


def test_recommendation_water_deficit_above_zero() -> None:
    # Vegetative Kc=0.70, ET₀=5mm, no recent rain, drip 0.85 efficiency
    # → demand = 3.50 mm, recommended = 3.50 / 0.85 ≈ 4.12 mm.
    out = compute_recommendation(_inputs())
    assert out.recommended_mm == Decimal("4.12")
    assert out.kc_used == Decimal("0.70")
    assert out.et0_mm_used == Decimal("5.00")


def test_recommendation_zero_when_rain_covers_demand() -> None:
    # 5mm rain in the last 2 days vs 3.50mm demand → no irrigation.
    out = compute_recommendation(_inputs(precip="5.0"))
    assert out.recommended_mm == Decimal("0.00")


def test_recommendation_clamps_at_zero_for_excess_rain() -> None:
    out = compute_recommendation(_inputs(precip="20.0"))
    assert out.recommended_mm == Decimal("0.00")


def test_recommendation_uses_growth_stage_kc() -> None:
    # Flowering Kc=1.10, ET₀=5mm, no rain, drip 0.85 → 5.50/0.85 = 6.47 mm
    out = compute_recommendation(_inputs(stage="flowering"))
    assert out.kc_used == Decimal("1.10")
    assert out.recommended_mm == Decimal("6.47")


def test_recommendation_rejects_zero_efficiency() -> None:
    with pytest.raises(ValueError, match="application_efficiency"):
        compute_recommendation(_inputs(eff="0"))


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


async def _seed_block_with_crop_and_weather(
    admin_session: AsyncSession,
    schema_name: str,
    *,
    et0_today: Decimal,
    precip_recent: Decimal,
    growth_stage: str | None,
) -> tuple[UUID, UUID]:
    """Insert farm + block + an active block_crops row + today's
    weather_derived_daily entry. Returns ``(farm_id, block_id)``."""
    farm_id = uuid4()
    block_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2, status) "
            "VALUES (:fid, 'PR7-FARM', 'PR-7 Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100, 'active')"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type, status, irrigation_system) "
            "VALUES (:bid, :fid, 'B-PR7', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'pr7-aoi-hash', 'block', 'active', 'drip')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )

    crop_id = (
        await admin_session.execute(
            text("SELECT id FROM public.crops WHERE is_active = TRUE LIMIT 1")
        )
    ).scalar_one()
    await admin_session.execute(
        text(
            "INSERT INTO block_crops "
            "(id, block_id, crop_id, season_label, growth_stage, is_current, status) "
            "VALUES (:aid, :bid, :cid, '2026-summer', :stage, TRUE, 'growing')"
        ).bindparams(
            bindparam("aid", type_=PG_UUID(as_uuid=True)),
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("cid", type_=PG_UUID(as_uuid=True)),
        ),
        {"aid": uuid4(), "bid": block_id, "cid": crop_id, "stage": growth_stage},
    )

    today = datetime.now(UTC).date()
    # Today's ET₀ row.
    await admin_session.execute(
        text(
            "INSERT INTO weather_derived_daily (farm_id, date, et0_mm_daily, precip_mm_daily) "
            "VALUES (:fid, :d, :et0, 0)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id, "d": today, "et0": et0_today},
    )
    # Yesterday's precip row to feed the rolling-precip window.
    await admin_session.execute(
        text(
            "INSERT INTO weather_derived_daily (farm_id, date, et0_mm_daily, precip_mm_daily) "
            "VALUES (:fid, :d, 0, :precip)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id, "d": today - timedelta(days=1), "precip": precip_recent},
    )
    await admin_session.commit()
    return farm_id, block_id


@pytest.mark.asyncio
async def test_generate_for_block_writes_pending_recommendation(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr7-generate",
        name="PR-7 Generate",
        contact_email="ops@pr7-generate.test",
    )
    _farm_id, block_id = await _seed_block_with_crop_and_weather(
        admin_session,
        tenant.schema_name,
        et0_today=Decimal("5.0"),
        precip_recent=Decimal("0.0"),
        growth_stage="vegetative",
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_irrigation_service(tenant_session=session, public_session=public_session)
            out = await svc.generate_for_block(
                block_id=block_id,
                scheduled_for=None,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
    assert out is not None
    assert out["status"] == "pending"
    # Drip 0.90 → demand = 0.70 * 5.0 = 3.50 mm; rec = 3.50 / 0.90 ≈ 3.89 mm.
    assert out["recommended_mm"] == Decimal("3.89")
    assert out["kc_used"] == Decimal("0.700")


@pytest.mark.asyncio
async def test_generate_is_idempotent_per_day(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr7-idempotent",
        name="PR-7 Idempotent",
        contact_email="ops@pr7-idemp.test",
    )
    _farm_id, block_id = await _seed_block_with_crop_and_weather(
        admin_session,
        tenant.schema_name,
        et0_today=Decimal("5.0"),
        precip_recent=Decimal("0.0"),
        growth_stage="vegetative",
    )

    factory = AsyncSessionLocal()
    outs = []
    for _ in range(2):
        async with factory() as session, session.begin():
            await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
            async with factory() as public_session:
                svc = get_irrigation_service(tenant_session=session, public_session=public_session)
                out = await svc.generate_for_block(
                    block_id=block_id,
                    scheduled_for=None,
                    actor_user_id=None,
                    tenant_schema=tenant.schema_name,
                )
                outs.append(out)
    assert outs[0] is not None, f"first generate returned None — outs={outs}"
    assert outs[1] is None, f"second generate should be a no-op, got {outs[1]}"

    count = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{tenant.schema_name}".irrigation_schedules '
                "WHERE block_id = :bid"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id},
        )
    ).scalar_one()
    assert count == 1, f"duplicate-pending-recommendation suppression failed, got {count}"


@pytest.mark.asyncio
async def test_apply_then_skip_transitions(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr7-transitions",
        name="PR-7 Transitions",
        contact_email="ops@pr7-trans.test",
    )
    _farm_id, block_id = await _seed_block_with_crop_and_weather(
        admin_session,
        tenant.schema_name,
        et0_today=Decimal("5.0"),
        precip_recent=Decimal("0.0"),
        growth_stage="vegetative",
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_irrigation_service(tenant_session=session, public_session=public_session)
            schedule = await svc.generate_for_block(
                block_id=block_id,
                scheduled_for=None,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
    assert schedule is not None
    schedule_id = schedule["id"]

    # Apply with the actual delivered volume.
    actor = uuid4()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_irrigation_service(tenant_session=session, public_session=public_session)
            applied = await svc.transition(
                schedule_id=schedule_id,
                action="apply",
                applied_volume_mm=Decimal("4.00"),
                notes="topped up to 4mm",
                actor_user_id=actor,
                tenant_schema=tenant.schema_name,
            )
    assert applied["status"] == "applied"
    assert applied["applied_volume_mm"] == Decimal("4.00")
    assert applied["applied_by"] == actor

    # Re-applying a non-pending schedule fails.
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_irrigation_service(tenant_session=session, public_session=public_session)
            with pytest.raises(Exception):  # noqa: B017, PT011 — status=applied path
                await svc.transition(
                    schedule_id=schedule_id,
                    action="skip",
                    applied_volume_mm=None,
                    notes=None,
                    actor_user_id=actor,
                    tenant_schema=tenant.schema_name,
                )


@pytest.mark.asyncio
async def test_block_without_current_crop_returns_none(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr7-no-crop",
        name="PR-7 No Crop",
        contact_email="ops@pr7-nc.test",
    )
    # Same seed shape but skip the block_crops insert by constructing manually.
    farm_id = uuid4()
    block_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2, status) "
            "VALUES (:fid, 'PR7-NC', 'PR-7 NC', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100, 'active')"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type, status, irrigation_system) "
            "VALUES (:bid, :fid, 'B-PR7-NC', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'pr7-nc-hash', 'block', 'active', 'drip')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.commit()

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_irrigation_service(tenant_session=session, public_session=public_session)
            out = await svc.generate_for_block(
                block_id=block_id,
                scheduled_for=None,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
    assert out is None
