"""A job stranded in `running` must be returned to `pending` and retried.

Production on 2026-08-23 held 7 imagery jobs in `running`, the oldest 575
hours old. Each one is a scene that will never land, because nothing in the
system can reach that row:

* re-discovery hits ``ON CONFLICT (subscription_id, scene_id) DO NOTHING``
* the re-dispatch query reads only ``status = 'pending'``
* ``acquire_scene`` returns a no-op for any job that is not ``pending``

Three of the seven blocks had no index rows at all for their scene day while
35 sibling blocks on the same farm had a full set, so this is missing data.

These tests run the real UPDATE statements against a real database. The two
SQL bugs found in this module during the platform-alerts work both survived
review because the only tests used a fake repository, and a fake cannot fail
on SQL that Postgres rejects.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.repository import ImageryRepository
from app.modules.tenancy.service import get_tenant_service

from .test_subscription_crud import _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.21 30.00,31.21 30.01,31.20 30.01,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.203 30.001,31.203 30.003,31.201 30.003,31.201 30.001))"


async def _tenant_with_one_block(admin_session: AsyncSession, slug: str) -> dict[str, Any]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    product_id = UUID(await _get_s2l2a_product_id(admin_session))
    farm_id, block_id, sub_id, farm_sub_id = uuid4(), uuid4(), uuid4(), uuid4()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'REAP', 'Reap farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :fid, 'B1', 'B1', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id), "wkt": _BLOCK},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_aoi_subscriptions (id, block_id, product_id, is_active) "
            "VALUES (:id, :bid, :pid, TRUE)"
        ),
        {"id": str(sub_id), "bid": str(block_id), "pid": str(product_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions (id, farm_id, product_id, is_active) "
            "VALUES (:id, :fid, :pid, TRUE)"
        ),
        {"id": str(farm_sub_id), "fid": str(farm_id), "pid": str(product_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_id": block_id,
        "sub_id": sub_id,
        "farm_sub_id": farm_sub_id,
        "product_id": product_id,
    }


async def _add_job(
    admin_session: AsyncSession,
    env: dict[str, Any],
    *,
    scene_id: str,
    status: str,
    age_hours: float,
    attempts: int = 0,
    farm_path: bool = False,
) -> UUID:
    job_id = uuid4()
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    if farm_path:
        await admin_session.execute(
            text(
                "INSERT INTO imagery_farm_ingestion_jobs "
                "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
                " requested_at, started_at, status, attempts) "
                "VALUES (:id, :sub, :fid, :pid, :scene, now(), "
                "        now() - make_interval(mins => :mins), now(), :st, :att)"
            ),
            {
                "id": str(job_id),
                "sub": str(env["farm_sub_id"]),
                "fid": str(env["farm_id"]),
                "pid": str(env["product_id"]),
                "scene": scene_id,
                "mins": int(age_hours * 60),
                "st": status,
                "att": attempts,
            },
        )
    else:
        await admin_session.execute(
            text(
                "INSERT INTO imagery_ingestion_jobs "
                "(id, subscription_id, block_id, product_id, scene_id, scene_datetime, "
                " requested_at, started_at, status, attempts) "
                "VALUES (:id, :sub, :bid, :pid, :scene, now(), "
                "        now() - make_interval(mins => :mins), now(), :st, :att)"
            ),
            {
                "id": str(job_id),
                "sub": str(env["sub_id"]),
                "bid": str(env["block_id"]),
                "pid": str(env["product_id"]),
                "scene": scene_id,
                "mins": int(age_hours * 60),
                "st": status,
                "att": attempts,
            },
        )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return job_id


async def _job(admin_session: AsyncSession, env: dict[str, Any], job_id: UUID) -> dict[str, Any]:
    row = (
        (
            await admin_session.execute(
                text(
                    f"SELECT status, attempts, started_at, error_code, error_message "
                    f'FROM "{env["schema"]}".imagery_ingestion_jobs WHERE id = :id'
                ),
                {"id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _repo_in(admin_session: AsyncSession, env: dict[str, Any]) -> ImageryRepository:
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    return ImageryRepository(admin_session)


@pytest.mark.asyncio
async def test_a_long_running_job_is_reset_to_pending(admin_session: AsyncSession) -> None:
    """The production case. `started_at` is cleared so the retried run reads
    like a first run rather than carrying the dead worker's state."""
    env = await _tenant_with_one_block(admin_session, "reap-running")
    job_id = await _add_job(admin_session, env, scene_id="S1", status="running", age_hours=575)

    repo = await _repo_in(admin_session, env)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    await admin_session.commit()

    assert reset == (job_id,)
    row = await _job(admin_session, env, job_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["started_at"] is None, "acquire_scene must see a job that has not started"


@pytest.mark.asyncio
async def test_a_recent_job_is_left_alone(admin_session: AsyncSession) -> None:
    """A job that is simply still working must not be pulled out from under
    the worker holding it."""
    env = await _tenant_with_one_block(admin_session, "reap-recent")
    job_id = await _add_job(admin_session, env, scene_id="S1", status="running", age_hours=1)

    repo = await _repo_in(admin_session, env)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    await admin_session.commit()

    assert reset == ()
    assert (await _job(admin_session, env, job_id))["status"] == "running"


@pytest.mark.asyncio
async def test_a_succeeded_job_is_never_touched(admin_session: AsyncSession) -> None:
    """Terminal is terminal. Re-running a succeeded job would refetch the
    scene and rewrite its assets for nothing."""
    env = await _tenant_with_one_block(admin_session, "reap-terminal")
    ok = await _add_job(admin_session, env, scene_id="S1", status="succeeded", age_hours=999)
    bad = await _add_job(admin_session, env, scene_id="S2", status="failed", age_hours=999)

    repo = await _repo_in(admin_session, env)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    await admin_session.commit()

    assert reset == ()
    assert (await _job(admin_session, env, ok))["status"] == "succeeded"
    assert (await _job(admin_session, env, bad))["status"] == "failed"


@pytest.mark.asyncio
async def test_the_attempt_cap_ends_the_loop(admin_session: AsyncSession) -> None:
    """Without a cap, a job that can never finish is reset every 10 minutes
    for ever. It becomes `failed` instead, so the failure detectors see it —
    a job quietly parked in `pending` is invisible to every detector we have.
    """
    env = await _tenant_with_one_block(admin_session, "reap-cap")
    job_id = await _add_job(
        admin_session, env, scene_id="S1", status="running", age_hours=575, attempts=3
    )

    repo = await _repo_in(admin_session, env)
    failed = await repo.fail_exhausted_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    await admin_session.commit()

    assert failed == 1
    assert reset == (), "a failed job must not also be reset in the same sweep"
    row = await _job(admin_session, env, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "stuck_no_progress"
    assert "3 attempt(s)" in row["error_message"]


@pytest.mark.asyncio
async def test_the_farm_path_is_reaped_too(admin_session: AsyncSession) -> None:
    """Thermal has no block-path rows at all, so a block-only reaper would
    leave every thermal job stranded."""
    env = await _tenant_with_one_block(admin_session, "reap-farm-path")
    job_id = await _add_job(
        admin_session, env, scene_id="S1", status="running", age_hours=575, farm_path=True
    )

    repo = await _repo_in(admin_session, env)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=True)
    await admin_session.commit()

    assert reset == (job_id,)
    status = (
        await admin_session.execute(
            text(
                f'SELECT status FROM "{env["schema"]}".imagery_farm_ingestion_jobs '
                "WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).scalar_one()
    assert status == "pending"


@pytest.mark.asyncio
async def test_a_stale_pending_job_is_retried(admin_session: AsyncSession) -> None:
    """A job whose dispatch was lost never had a worker at all. It sits in
    `pending` and no discovery run will ever queue it again, because
    re-discovery of the same scene returns created=False."""
    env = await _tenant_with_one_block(admin_session, "reap-pending")
    job_id = await _add_job(admin_session, env, scene_id="S1", status="pending", age_hours=48)

    repo = await _repo_in(admin_session, env)
    reset = await repo.reset_stuck_jobs(stuck_hours=6, max_attempts=3, farm_path=False)
    await admin_session.commit()

    assert reset == (job_id,)
    assert (await _job(admin_session, env, job_id))["attempts"] == 1
