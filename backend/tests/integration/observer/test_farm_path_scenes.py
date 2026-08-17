"""The Observer has to show whole-farm acquisitions, thermal included.

`job_stage_counts` learned about `imagery_farm_ingestion_jobs` when the
farm path shipped; the histogram and the scene table did not. The result
was one screen contradicting itself: the ribbon reported N scenes
acquired and the table beneath it listed none, on the same farm, in the
same window.

For thermal that was total. `landsat_c2_l2_st` is farm-AOI only by
construction — measured on production 2026-08-17, the tenant had 30
succeeded thermal farm jobs, 2,372 thermal aggregate rows across
lst/cwsi/smi, and **zero** rows in `imagery_ingestion_jobs` for that
product. So the Scenes tab had never displayed a thermal scene, and the
histogram had never drawn a thermal bar, since the day thermal shipped.

These tests seed a thermal farm subscription with farm jobs on top of the
standard block scenario, then assert that:

  * the farm rows appear, carry `scope = 'farm'` and a null `block_id`;
  * their index counts roll up across the farm's blocks;
  * the block rows are untouched, which is the regression that matters
    for every tenant that has not cut over;
  * the ribbon and the table now agree on how many scenes exist.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import PlatformRole
from app.shared.db.ids import uuid7

from .conftest import WINDOW_FROM, WINDOW_TO, Scenario, build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/observer"

# Three thermal acquisitions inside the seeded window, spaced so each
# lands in its own daily bucket.
_THERMAL_SCENES = 3
_THERMAL_INDEX_CODES = ("lst", "cwsi", "smi")


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _window() -> dict[str, str]:
    return {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()}


async def _seed_thermal_farm_path(
    session: AsyncSession, scenario: Scenario
) -> tuple[UUID, list[UUID]]:
    """A thermal farm subscription, its jobs, and the aggregates they caused.

    Aggregates go on `block_a` only. One farm fetch produces per-block
    aggregates through the zonal pass, and seeding just one block is what
    lets the roll-up assertion distinguish "summed across the farm" from
    "counted once".
    """
    await session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))
    product_id = UUID(
        str(
            (
                await session.execute(
                    text(
                        "SELECT id FROM public.imagery_products " "WHERE code = 'landsat_c2_l2_st'"
                    )
                )
            ).scalar_one()
        )
    )
    sub_id = uuid7()
    await session.execute(
        text(
            """
            INSERT INTO imagery_farm_subscriptions
              (id, farm_id, product_id, is_active, fetch_farm_aoi)
            VALUES (:id, :farm, :prod, TRUE, TRUE)
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": sub_id, "farm": scenario.farm_id, "prod": product_id},
    )

    job_ids: list[UUID] = []
    for i in range(_THERMAL_SCENES):
        scene_dt = WINDOW_FROM + timedelta(days=i * 3, hours=8)
        scene_id = f"LC09_OBS_{i:02d}"
        job_id = uuid7()
        job_ids.append(job_id)
        await session.execute(
            text(
                """
                INSERT INTO imagery_farm_ingestion_jobs (
                    id, subscription_id, farm_id, product_id, scene_id,
                    scene_datetime, status, stac_item_id, cloud_cover_pct,
                    requested_at, started_at, completed_at
                ) VALUES (
                    :id, :sub, :farm, :prod, :scene,
                    :sdt, 'succeeded', :scene, 3.1,
                    :sdt, :sdt, :sdt
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("sub", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("prod", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": job_id,
                "sub": sub_id,
                "farm": scenario.farm_id,
                "prod": product_id,
                "scene": scene_id,
                "sdt": scene_dt,
            },
        )
        for code in _THERMAL_INDEX_CODES:
            await session.execute(
                text(
                    """
                    INSERT INTO block_index_aggregates (
                        time, block_id, index_code, product_id, mean, min, max,
                        p10, p50, p90, std_dev, valid_pixel_count,
                        total_pixel_count, cloud_cover_pct, stac_item_id
                    ) VALUES (
                        :t, :block, :code, :prod, 41.20, 38.10, 45.90,
                        39.00, 41.10, 43.80, 1.4200, 812,
                        860, 3.1, :stac
                    )
                    """
                ).bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True)),
                    bindparam("prod", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "t": scene_dt,
                    "block": scenario.block_a,
                    "code": code,
                    "prod": product_id,
                    "stac": scene_id,
                },
            )
    await session.commit()
    await session.execute(text("SET search_path TO public"))
    return product_id, job_ids


async def _scenes(scenario: Scenario, product_id: UUID | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "farm_id": str(scenario.farm_id),
        **_window(),
        "limit": 200,
    }
    if product_id is not None:
        params["product"] = str(product_id)
    async with _platform_client() as client:
        resp = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes", params=params)
    assert resp.status_code == 200, resp.text
    return list(resp.json())


@pytest.mark.asyncio
async def test_thermal_scenes_are_listed_at_all(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """The headline: before this, a thermal farm had an empty Scenes tab."""
    product_id, _ = await _seed_thermal_farm_path(admin_session, scenario)

    rows = await _scenes(scenario, product_id)
    assert len(rows) == _THERMAL_SCENES
    assert {r["scene_id"] for r in rows} == {f"LC09_OBS_{i:02d}" for i in range(_THERMAL_SCENES)}


@pytest.mark.asyncio
async def test_a_farm_row_names_its_scope_and_carries_no_block(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """One fetch covers every block, so naming one of them would be a fiction."""
    product_id, _ = await _seed_thermal_farm_path(admin_session, scenario)

    row = (await _scenes(scenario, product_id))[0]
    assert row["scope"] == "farm"
    assert row["block_id"] is None
    # The column still says what was fetched — the farm's own name.
    assert row["block_name"] == "Observer Farm"
    # No `valid_pixel_pct` is recorded for a farm job; null is the truth,
    # and 0 would read as "every pixel was unusable".
    assert row["valid_pixel_pct"] is None


@pytest.mark.asyncio
async def test_a_farm_rows_index_count_rolls_up_across_the_farm(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """Three thermal codes were written on one block by one acquisition."""
    product_id, _ = await _seed_thermal_farm_path(admin_session, scenario)

    row = (await _scenes(scenario, product_id))[0]
    assert row["indices_written"] == len(_THERMAL_INDEX_CODES)


@pytest.mark.asyncio
async def test_block_scenes_are_unchanged(admin_session: AsyncSession, scenario: Scenario) -> None:
    """The regression guard: the block path must not gain or lose a row.

    The seeded Sentinel-2 scenario is 8 block jobs across two blocks; the
    thermal farm jobs are on a different product and must not touch it.
    """
    await _seed_thermal_farm_path(admin_session, scenario)

    rows = await _scenes(scenario, scenario.product_id)
    assert len(rows) == 8
    assert all(r["scope"] == "block" for r in rows)
    assert all(r["block_id"] is not None for r in rows)


@pytest.mark.asyncio
async def test_the_ribbon_and_the_table_agree(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """They disagreed by construction: one counted both paths, one did not.

    A ribbon reading "3 discovered" above an empty table is worse than
    either number alone — it reads as a pipeline that lost its scenes.
    """
    product_id, _ = await _seed_thermal_farm_path(admin_session, scenario)

    async with _platform_client() as client:
        overview = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/overview",
            params={
                "farm_id": str(scenario.farm_id),
                "product": str(product_id),
                **_window(),
            },
        )
    assert overview.status_code == 200, overview.text
    discovered = next(s for s in overview.json()["stages"] if s["key"] == "discovered")["count"]

    assert discovered == len(await _scenes(scenario, product_id)) == _THERMAL_SCENES


@pytest.mark.asyncio
async def test_the_histogram_draws_thermal_buckets(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    product_id, _ = await _seed_thermal_farm_path(admin_session, scenario)

    async with _platform_client() as client:
        resp = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/histogram",
            params={
                "farm_id": str(scenario.farm_id),
                "product": str(product_id),
                "bucket": "day",
                **_window(),
            },
        )
    assert resp.status_code == 200, resp.text
    buckets = resp.json()
    assert len(buckets) == _THERMAL_SCENES
    # Every seeded scene succeeded AND wrote aggregates, so all three land
    # in `computed` rather than `acquired_only`.
    assert sum(b["computed"] for b in buckets) == _THERMAL_SCENES
    assert sum(b["acquired_only"] for b in buckets) == 0


@pytest.mark.asyncio
async def test_a_farm_scene_opens_in_the_detail_view(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """A row you cannot click is only half a fix."""
    _, job_ids = await _seed_thermal_farm_path(admin_session, scenario)

    async with _platform_client() as client:
        resp = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_ids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "farm"
    assert body["block_id"] is None
    assert body["product_code"] == "landsat_c2_l2_st"
    # The AOI is the farm's, so the asset key must resolve off the farm's
    # own hash — a block's would point at an object nothing ever wrote.
    assert body["aoi_hash"]
    # A grid belongs to a block; this scene spans all of them.
    assert body["grid"] is None


@pytest.mark.asyncio
async def test_a_thermal_scene_reports_the_landsat_mask_ruleset(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """It claimed `s2_scl_v1` — a ruleset that cannot read a QA_PIXEL band.

    The panel's whole claim is that it cannot describe rules the pipeline
    is not running, and on thermal it was doing exactly that.
    """
    _, job_ids = await _seed_thermal_farm_path(admin_session, scenario)

    async with _platform_client() as client:
        resp = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_ids[0]}")
    body = resp.json()
    assert body["mask_ruleset"] == "landsat_qa_pixel_v1"
    # Bits, not classes — different encodings, so only one is populated.
    assert body["mask_bits"] == [0, 1, 2, 3, 4, 5]
    assert body["mask_classes"] == []


@pytest.mark.asyncio
async def test_a_block_scene_still_reports_the_sentinel_ruleset(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    rows = await _scenes(scenario, scenario.product_id)
    async with _platform_client() as client:
        resp = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{rows[0]['job_id']}")
    body = resp.json()
    assert body["mask_ruleset"] == "s2_scl_v1"
    assert body["mask_classes"] == [0, 1, 3, 8, 9, 10, 11]
    assert body["mask_bits"] == []


@pytest.mark.asyncio
async def test_verifying_a_farm_scene_is_refused_with_a_reason(
    admin_session: AsyncSession, scenario: Scenario
) -> None:
    """Verification diffs against one block's stored rows; a farm scene has none.

    422 rather than 404: the id is right and the scene is real, so sending
    the operator to look for a missing row would be the wrong instruction.
    """
    _, job_ids = await _seed_thermal_farm_path(admin_session, scenario)

    async with _platform_client() as client:
        resp = await client.post(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_ids[0]}:verify",
            params={"mode": "fast"},
        )
    assert resp.status_code == 422, resp.text
    assert "whole-farm" in resp.text
