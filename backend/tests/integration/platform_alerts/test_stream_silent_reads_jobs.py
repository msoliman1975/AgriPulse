"""`stream_silent` must measure what the stream produced, not a watermark.

Until 2026-08-23 the detector read
``imagery_farm_subscriptions.last_successful_ingest_at``. Production showed
both ways that column lies:

* Mango Republic had 216 succeeded optical jobs and 217 succeeded thermal
  jobs, the newest finished 29 hours earlier, and the column was still NULL.
  A backfill never writes it (``bump_watermark=False``) and a live poll only
  bumps it when it CREATED a job, so a farm whose backfill already covered
  every published scene stays NULL until the next new pass. The page said the
  farm had never worked.
* The column is stamped when a poll queues work, not when the work succeeds,
  so a farm whose jobs all fail reads as healthy.

No test ran this SQL before. Both production SQL bugs found in this area
survived review because the only tests used a fake repository, so these run
the real statement against a real database.
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
    detect_stream_silent,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.21 30.00,31.21 30.01,31.20 30.01,31.20 30.00))"

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
)


async def _farm_on_the_farm_path(admin_session: AsyncSession, slug: str) -> dict[str, Any]:
    """One farm, one active farm-level optical subscription, no jobs yet.

    `last_successful_ingest_at` is left NULL, which is what production had.
    """
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
    farm_id, sub_id = uuid4(), uuid4()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'SIL', 'Silent farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions (id, farm_id, product_id, is_active) "
            "VALUES (:id, :fid, :pid, TRUE)"
        ),
        {"id": str(sub_id), "fid": str(farm_id), "pid": str(product_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"schema": schema, "farm_id": farm_id, "sub_id": sub_id, "product_id": product_id}


async def _add_farm_job(
    admin_session: AsyncSession,
    env: dict[str, Any],
    *,
    scene_id: str,
    status: str,
    completed_hours_ago: float | None,
) -> None:
    # `completed_at` is computed here rather than in SQL. A bare `:mins` bind
    # inside a CASE gives asyncpg no way to infer the parameter type, and it
    # raises AmbiguousParameterError.
    completed_at = (
        None
        if completed_hours_ago is None
        else datetime.now(UTC) - timedelta(hours=completed_hours_ago)
    )
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_ingestion_jobs "
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " completed_at, status) "
            "VALUES (:id, :sub, :fid, :pid, :scene, now(), :done, :st)"
        ),
        {
            "id": str(uuid4()),
            "sub": str(env["sub_id"]),
            "fid": str(env["farm_id"]),
            "pid": str(env["product_id"]),
            "scene": scene_id,
            "done": completed_at,
            "st": status,
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()


async def _optical_findings(admin_session: AsyncSession, env: dict[str, Any]) -> list[Any]:
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    found = await detect_stream_silent(admin_session, tenant_key=env["schema"], th=TH)
    await admin_session.execute(text("SET search_path TO public"))
    return [f for f in found if f.context.get("stream") == STREAM_OPTICAL]


@pytest.mark.asyncio
async def test_a_backfilled_farm_with_a_null_watermark_does_not_alert(
    admin_session: AsyncSession,
) -> None:
    """The Mango Republic case, and the reason for this change."""
    env = await _farm_on_the_farm_path(admin_session, "silent-backfilled")
    await _add_farm_job(
        admin_session, env, scene_id="S1", status="succeeded", completed_hours_ago=29
    )

    assert await _optical_findings(admin_session, env) == []

    watermark = (
        await admin_session.execute(
            text(
                f"SELECT last_successful_ingest_at "
                f'FROM "{env["schema"]}".imagery_farm_subscriptions WHERE id = :id'
            ),
            {"id": env["sub_id"]},
        )
    ).scalar_one()
    assert watermark is None, "the old read would have called this farm dead"


@pytest.mark.asyncio
async def test_a_farm_whose_jobs_all_fail_does_alert(admin_session: AsyncSession) -> None:
    """The direction that matters more. The watermark is stamped when a poll
    queues work, so under the old read this farm looked healthy."""
    env = await _farm_on_the_farm_path(admin_session, "silent-all-failed")
    await _add_farm_job(admin_session, env, scene_id="S1", status="failed", completed_hours_ago=2)
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    await admin_session.execute(
        text(
            "UPDATE imagery_farm_subscriptions SET last_successful_ingest_at = now() "
            "WHERE id = :id"
        ),
        {"id": env["sub_id"]},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    findings = await _optical_findings(admin_session, env)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].context["last_success_at"] is None


@pytest.mark.asyncio
async def test_a_stale_success_still_alerts_on_its_ceiling(
    admin_session: AsyncSession,
) -> None:
    """The detector must keep working, not just stop firing."""
    env = await _farm_on_the_farm_path(admin_session, "silent-stale")
    await _add_farm_job(
        admin_session, env, scene_id="S1", status="succeeded", completed_hours_ago=300
    )

    findings = await _optical_findings(admin_session, env)
    assert len(findings) == 1
    assert findings[0].severity == "critical", "300h is past the 240h optical ceiling"
    assert findings[0].context["last_success_at"] is not None


@pytest.mark.asyncio
async def test_an_inactive_subscription_never_alerts(admin_session: AsyncSession) -> None:
    """A stream with no active feed is switched off, not silent."""
    env = await _farm_on_the_farm_path(admin_session, "silent-inactive")
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    await admin_session.execute(
        text("UPDATE imagery_farm_subscriptions SET is_active = FALSE WHERE id = :id"),
        {"id": env["sub_id"]},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    assert await _optical_findings(admin_session, env) == []
