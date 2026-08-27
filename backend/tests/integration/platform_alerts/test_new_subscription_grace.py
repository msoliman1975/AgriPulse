"""A subscription switched on minutes ago is not yet a failure.

Production, 2026-08-25. Thermal was enabled on farm B-Elkair-Suez
(`imagery_farm_subscriptions.created_at = 07:20:41`). The
`platform_alerts.sweep` that ran at 07:21 opened two rows against it:

* critical, `peer_lag` — "B-Elkair-Suez is behind other farms on
  landsat_c2_l2_st. Scene day 2026-08-15 was ingested for 1 other farm in
  this tenant 5.9 days ago" — naming a scene day six days older than the
  subscription itself.
* warning, `stream_silent` — "Thermal has never completed successfully for
  this farm. Check that the subscription was provisioned."

The hourly discovery poll first ran at 07:31 and the first jobs succeeded at
07:33, so both rows described the ten minutes before anything had run. An
operator enabling a product on a farm cannot avoid this, which makes every
such change look like an incident.

Two guards, one per detector:

* `peer_lag` only compares against a scene the peer ingested AFTER this farm
  subscribed. You cannot be behind on a pass that predates your feed.
* `stream_silent` gives a new subscription `new_subscription_grace_hours`
  before "never succeeded" counts, and only while nothing has been attempted
  at all. A farm whose jobs are failing still alerts immediately — that is a
  fault, not a cold start.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_alerts.detectors import (
    STREAM_OPTICAL,
    Thresholds,
    detect_peer_lag,
    detect_stream_silent,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM_A = "POLYGON((31.20 30.00,31.21 30.00,31.21 30.01,31.20 30.01,31.20 30.00))"
_FARM_B = "POLYGON((31.30 30.00,31.31 30.00,31.31 30.01,31.30 30.01,31.30 30.00))"

# Inside `farm_scene`'s 30-day window, and old enough that the peer's ingest
# is well past `peer_lag_hours`.
_SCENE_DAY = datetime.now(UTC) - timedelta(days=5)

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


async def _tenant(admin_session: AsyncSession, slug: str) -> tuple[str, UUID]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    product_id = UUID(
        str(
            (
                await admin_session.execute(
                    text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
                )
            ).scalar_one()
        )
    )
    return tenant.schema_name, product_id


async def _farm_with_subscription(
    admin_session: AsyncSession,
    *,
    schema: str,
    product_id: UUID,
    code: str,
    wkt: str,
    subscribed_hours_ago: float,
) -> tuple[UUID, UUID]:
    """One farm, one active farm-level subscription of a given age."""
    farm_id, sub_id = uuid4(), uuid4()
    created_at = datetime.now(UTC) - timedelta(hours=subscribed_hours_ago)
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, :code, :code, ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "code": code, "wkt": wkt},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions "
            "(id, farm_id, product_id, is_active, created_at) "
            "VALUES (:id, :fid, :pid, TRUE, :created)"
        ),
        {
            "id": str(sub_id),
            "fid": str(farm_id),
            "pid": str(product_id),
            "created": created_at,
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return farm_id, sub_id


async def _succeeded_job(
    admin_session: AsyncSession,
    *,
    schema: str,
    sub_id: UUID,
    farm_id: UUID,
    product_id: UUID,
    scene_day: datetime,
    completed_hours_ago: float,
) -> None:
    completed_at = datetime.now(UTC) - timedelta(hours=completed_hours_ago)
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_ingestion_jobs "
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " completed_at, status) "
            "VALUES (:id, :sub, :fid, :pid, :scene, :sd, :done, 'succeeded')"
        ),
        {
            "id": str(uuid4()),
            "sub": str(sub_id),
            "fid": str(farm_id),
            "pid": str(product_id),
            "scene": f"{scene_day:%Y-%m-%d}-{uuid4().hex[:6]}",
            "sd": scene_day,
            "done": completed_at,
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()


async def _silent(admin_session: AsyncSession, schema: str) -> list[Any]:
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    found = await detect_stream_silent(admin_session, tenant_key=schema, th=TH)
    await admin_session.execute(text("SET search_path TO public"))
    return [f for f in found if f.context.get("stream") == STREAM_OPTICAL]


async def _peer(admin_session: AsyncSession, schema: str) -> list[Any]:
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    found = await detect_peer_lag(admin_session, tenant_key=schema, th=TH)
    await admin_session.execute(text("SET search_path TO public"))
    return found


@pytest.mark.asyncio
async def test_a_subscription_created_minutes_ago_is_not_silent(
    admin_session: AsyncSession,
) -> None:
    schema, product_id = await _tenant(admin_session, "grace-fresh")
    await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="NEW",
        wkt=_FARM_A,
        subscribed_hours_ago=0.2,
    )

    assert await _silent(admin_session, schema) == []


@pytest.mark.asyncio
async def test_the_same_subscription_is_silent_once_the_grace_expires(
    admin_session: AsyncSession,
) -> None:
    """The guard must delay the alert, not remove it."""
    schema, product_id = await _tenant(admin_session, "grace-expired")
    await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="OLD",
        wkt=_FARM_A,
        subscribed_hours_ago=48,
    )

    findings = await _silent(admin_session, schema)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].context["last_success_at"] is None


@pytest.mark.asyncio
async def test_a_farm_is_not_behind_on_a_scene_older_than_its_subscription(
    admin_session: AsyncSession,
) -> None:
    """The critical alert this change exists to stop.

    The peer holds a scene day it ingested three days ago. The second farm
    subscribed one minute ago, so it has nothing — and cannot have anything,
    because the discovery poll has not run.
    """
    schema, product_id = await _tenant(admin_session, "peer-fresh")
    peer_farm, peer_sub = await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="PEER",
        wkt=_FARM_A,
        subscribed_hours_ago=500,
    )
    await _succeeded_job(
        admin_session,
        schema=schema,
        sub_id=peer_sub,
        farm_id=peer_farm,
        product_id=product_id,
        scene_day=_SCENE_DAY,
        completed_hours_ago=72,
    )
    await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="LATE",
        wkt=_FARM_B,
        subscribed_hours_ago=0.02,
    )

    assert await _peer(admin_session, schema) == []


@pytest.mark.asyncio
async def test_a_farm_subscribed_before_the_peer_ingested_still_lags(
    admin_session: AsyncSession,
) -> None:
    """The direction that matters. Same shape, but the second farm has had a
    subscription since long before the peer got the scene."""
    schema, product_id = await _tenant(admin_session, "peer-real")
    peer_farm, peer_sub = await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="PEER",
        wkt=_FARM_A,
        subscribed_hours_ago=500,
    )
    await _succeeded_job(
        admin_session,
        schema=schema,
        sub_id=peer_sub,
        farm_id=peer_farm,
        product_id=product_id,
        scene_day=_SCENE_DAY,
        completed_hours_ago=72,
    )
    await _farm_with_subscription(
        admin_session,
        schema=schema,
        product_id=product_id,
        code="BEHIND",
        wkt=_FARM_B,
        subscribed_hours_ago=400,
    )

    findings = await _peer(admin_session, schema)
    assert len(findings) == 1
    assert findings[0].farm_name == "BEHIND"
