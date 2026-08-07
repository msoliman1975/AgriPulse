"""Shared fixtures for Observer integration tests.

Two halves.

**App wiring** — same shape as the backfill suite: mount only the Observer
router behind a stubbed auth middleware, so the capability dependency is
exercised on the real route path without Keycloak.

**A seeded scenario** — deliberately *not* "find whatever is in the fixture
DB and skip if there isn't any". Every number the ribbon reports is a ratio
between two populations, and a test that skips when the data is thin proves
nothing about those ratios; #331 shipped a 500 to production behind exactly
that pattern (5 of 6 tests skipped). So `scenario` builds a known farm with
known defects and the tests assert exact counts against it.

The scenario, all on one Sentinel-2 L2A product:

  Block A — has a grid config governing all time (24 cells)
      4 succeeded jobs, of which 3 wrote block aggregates
        (the 4th is the "downloaded fine, compute_indices died" case)
      2 of those 3 also wrote cell aggregates
      1 failed job
      1 skipped_cloud job
  Block B — no grid config at all
      2 succeeded jobs, both wrote block aggregates
      (so cell aggregates are *not applicable* here, not missing)

Which makes the expected ribbon, over the seeded window:

  discovered 8 · acquired 6 (of 7 non-skipped) · indices 5 (of 6)
  cells 2 produced of 4 expected — the denominator counts only Block A
  consumers 0
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.imagery.router import router as imagery_router
from app.modules.observer.router import router as observer_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import (
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.db.ids import uuid7

# Anchor the scenario in the past so "now" never drifts into it.
WINDOW_FROM = datetime(2026, 5, 1, tzinfo=UTC)
WINDOW_TO = datetime(2026, 6, 1, tzinfo=UTC)

INDEX_CODES = ("ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi")


class StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(observer_router)
    app.add_middleware(StubAuth, context=context)
    return app


def build_seeding_app(context: RequestContext) -> FastAPI:
    """Farms + imagery routers, used only to create the scenario's fixtures.

    Going through the API rather than raw SQL for farms and blocks keeps the
    geometry, UTM projection and aoi_hash derivation identical to production.
    """
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(imagery_router)
    app.add_middleware(StubAuth, context=context)
    return app


def make_context(
    *,
    user_id: UUID,
    tenant_id: UUID | None,
    tenant_role: TenantRole | None = None,
    platform_role: PlatformRole | None = None,
    farm_scopes: tuple[FarmScope, ...] = (),
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        platform_role=platform_role,
        farm_scopes=farm_scopes,
    )


@dataclass(frozen=True)
class Scenario:
    tenant_id: UUID
    tenant_schema: str
    farm_id: UUID
    block_a: UUID  # gridded
    block_b: UUID  # ungridded
    product_id: UUID


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


def _multipoly(lon: float, lat: float, side: float = 0.02) -> dict[str, object]:
    return {"type": "MultiPolygon", "coordinates": [_square(lon, lat, side)["coordinates"]]}


async def _create_user(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "Observer Test User",
        },
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": uuid4(), "uid": user_id, "tid": tenant_id},
    )
    await session.commit()


async def _insert_job(
    session: AsyncSession,
    *,
    subscription_id: UUID,
    block_id: UUID,
    product_id: UUID,
    scene_id: str,
    scene_dt: datetime,
    status: str,
    stac_item_id: str | None,
    cloud: float | None = 4.2,
    valid_pct: float | None = 91.6,
    error_code: str | None = None,
) -> UUID:
    job_id = uuid7()
    await session.execute(
        text(
            """
            INSERT INTO imagery_ingestion_jobs (
                id, subscription_id, block_id, product_id, scene_id,
                scene_datetime, status, stac_item_id, cloud_cover_pct,
                valid_pixel_pct, error_code, requested_at, started_at, completed_at
            ) VALUES (
                :id, :sub, :block, :prod, :scene,
                :sdt, :status, :stac, :cloud,
                :vpct, :ecode, :sdt, :sdt, :sdt
            )
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("sub", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": job_id,
            "sub": subscription_id,
            "block": block_id,
            "prod": product_id,
            "scene": scene_id,
            "sdt": scene_dt,
            "status": status,
            "stac": stac_item_id,
            "cloud": cloud,
            "vpct": valid_pct,
            "ecode": error_code,
        },
    )
    return job_id


async def _insert_block_aggregates(
    session: AsyncSession,
    *,
    block_id: UUID,
    product_id: UUID,
    scene_dt: datetime,
    stac_item_id: str,
) -> None:
    for code in INDEX_CODES:
        await session.execute(
            text(
                """
                INSERT INTO block_index_aggregates (
                    time, block_id, index_code, product_id, mean, min, max,
                    p10, p50, p90, std_dev, valid_pixel_count,
                    total_pixel_count, cloud_cover_pct, stac_item_id
                ) VALUES (
                    :t, :block, :code, :prod, 0.5123, 0.0412, 0.8104,
                    0.3110, 0.5240, 0.6902, 0.1284, 3214,
                    3508, 4.2, :stac
                )
                """
            ).bindparams(
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("prod", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "t": scene_dt,
                "block": block_id,
                "code": code,
                "prod": product_id,
                "stac": stac_item_id,
            },
        )


async def _insert_grid(
    session: AsyncSession,
    *,
    block_id: UUID,
    product_id: UUID,
    cells: int = 4,
) -> list[UUID]:
    """A grid config governing all time, plus `cells` square cells."""
    config_id = uuid7()
    await session.execute(
        text(
            """
            INSERT INTO grid_configs (id, block_id, product_id, cell_size_m, utm_srid)
            VALUES (:id, :block, :prod, 40.0, 32636)
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": config_id, "block": block_id, "prod": product_id},
    )
    cell_ids: list[UUID] = []
    for i in range(cells):
        cell_id = uuid7()
        cell_ids.append(cell_id)
        await session.execute(
            text(
                """
                INSERT INTO grid_cells (
                    id, grid_config_id, row_idx, col_idx, geom, centroid, area_m2
                ) VALUES (
                    :id, :cfg, :r, :c,
                    ST_GeomFromText(:wkt, 32636),
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                    1600.0
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("cfg", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": cell_id,
                "cfg": config_id,
                "r": i // 2,
                "c": i % 2,
                "wkt": (
                    f"POLYGON(({330000 + i * 40} 3320000, {330040 + i * 40} 3320000, "
                    f"{330040 + i * 40} 3320040, {330000 + i * 40} 3320040, "
                    f"{330000 + i * 40} 3320000))"
                ),
                "lon": 31.21 + i * 0.0004,
                "lat": 30.01,
            },
        )
    return cell_ids


async def _insert_cell_aggregates(
    session: AsyncSession,
    *,
    block_id: UUID,
    product_id: UUID,
    scene_dt: datetime,
    stac_item_id: str,
    cell_ids: list[UUID],
) -> None:
    for cell_id in cell_ids:
        for code in INDEX_CODES:
            await session.execute(
                text(
                    """
                    INSERT INTO block_grid_aggregates (
                        time, block_id, cell_id, index_code, product_id,
                        mean, min, max, std_dev, valid_pixel_count,
                        total_pixel_count, cloud_cover_pct, stac_item_id
                    ) VALUES (
                        :t, :block, :cell, :code, :prod,
                        0.5490, 0.1, 0.8, 0.1, 146,
                        160, 4.2, :stac
                    )
                    """
                ).bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True)),
                    bindparam("cell", type_=PG_UUID(as_uuid=True)),
                    bindparam("prod", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "t": scene_dt,
                    "block": block_id,
                    "cell": cell_id,
                    "code": code,
                    "prod": product_id,
                    "stac": stac_item_id,
                },
            )


async def _insert_calc_run(
    session: AsyncSession,
    *,
    job_id: UUID,
    block_id: UUID,
    product_id: UUID,
    scene_dt: datetime,
    scene_id: str,
    calc_version: str,
    outcome: str = "ok",
    error: str | None = None,
    per_index: str = '{"ndvi": {"valid": 3214, "total": 3508, "nodata": 55, "mean": 0.5123}}',
) -> None:
    """One `indices_calc_runs` row (tenant migration 0060)."""
    await session.execute(
        text(
            """
            INSERT INTO indices_calc_runs (
                job_id, scene_time, scene_id, stac_item_id,
                block_id, product_id, aoi_hash,
                calc_version, mask_ruleset, band_order,
                aoi_pixel_count, masked_pixel_count, per_index,
                trigger, outcome, error, started_at, completed_at, duration_ms
            ) VALUES (
                :job, :t, :scene, :scene,
                :block, :prod, 'a41f9c',
                :ver, 's2_scl_v1', ARRAY['red', 'nir']::text[],
                3508, 239, CAST(:per_index AS jsonb),
                'live', :outcome, :error, :t, :t, 18400
            )
            """
        ).bindparams(
            bindparam("job", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "job": job_id,
            "t": scene_dt,
            "scene": scene_id,
            "block": block_id,
            "prod": product_id,
            "ver": calc_version,
            "outcome": outcome,
            "error": error,
            "per_index": per_index,
        },
    )


@pytest.fixture
async def scenario(admin_session: AsyncSession) -> Scenario:
    """Build the farm described in this module's docstring."""
    session = admin_session
    tenancy = get_tenant_service(session)
    tenant = await tenancy.create_tenant(
        slug=f"obs-{uuid4().hex[:8]}",
        name="Observer Scenario",
        contact_email="ops@observer.test",
    )
    user_id = uuid4()
    await _create_user(session, tenant_id=tenant.tenant_id, user_id=user_id)

    seeding_ctx = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    async with AsyncClient(
        transport=ASGITransport(app=build_seeding_app(seeding_ctx)),
        base_url="http://test",
    ) as client:
        farm = await client.post(
            "/api/v1/farms",
            json={
                "code": "FARM-OBS-1",
                "name": "Observer Farm",
                "boundary": _multipoly(31.2, 30.0),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = UUID(farm.json()["id"])

        blocks: list[UUID] = []
        for i, code in enumerate(("B-OBS-A", "B-OBS-B")):
            resp = await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": code, "boundary": _square(31.21 + i * 0.006, 30.01)},
            )
            assert resp.status_code == 201, resp.text
            blocks.append(UUID(resp.json()["id"]))
        block_a, block_b = blocks

        product_id = UUID(
            str(
                (
                    await session.execute(
                        text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
                    )
                ).scalar_one()
            )
        )
        subs: dict[UUID, UUID] = {}
        for block_id in (block_a, block_b):
            resp = await client.post(
                f"/api/v1/blocks/{block_id}/imagery/subscriptions",
                json={"product_id": str(product_id)},
            )
            assert resp.status_code == 201, resp.text
            subs[block_id] = UUID(resp.json()["id"])

    # Everything below is raw SQL in the tenant schema: these are pipeline
    # *outputs*, and there is no API that writes them.
    await session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

    cell_ids = await _insert_grid(session, block_id=block_a, product_id=product_id)

    # Block A — 4 succeeded, 3 with aggregates, 2 of those with cells.
    for i in range(4):
        scene_dt = WINDOW_FROM + timedelta(days=i * 2)
        stac = f"S2A_OBS_A_{i:02d}"
        job_id = await _insert_job(
            session,
            subscription_id=subs[block_a],
            block_id=block_a,
            product_id=product_id,
            scene_id=stac,
            scene_dt=scene_dt,
            status="succeeded",
            stac_item_id=stac,
        )
        if i == 0:
            # Two executions of the same scene, oldest first. This is what a
            # recompute leaves behind: the aggregate row now holds the newer
            # numbers and says nothing about having been replaced.
            await _insert_calc_run(
                session,
                job_id=job_id,
                block_id=block_a,
                product_id=product_id,
                scene_dt=scene_dt,
                scene_id=stac,
                calc_version="idx-2026.03",
            )
            await _insert_calc_run(
                session,
                job_id=job_id,
                block_id=block_a,
                product_id=product_id,
                scene_dt=scene_dt,
                scene_id=stac,
                calc_version="idx-2026.08",
            )
        elif i == 3:
            # The scene that downloaded and then died in compute_indices.
            await _insert_calc_run(
                session,
                job_id=job_id,
                block_id=block_a,
                product_id=product_id,
                scene_dt=scene_dt,
                scene_id=stac,
                calc_version="idx-2026.08",
                outcome="failed",
                error="compute_indices_failed: rasterio could not open the asset",
                per_index="{}",
            )
        if i < 3:
            await _insert_block_aggregates(
                session,
                block_id=block_a,
                product_id=product_id,
                scene_dt=scene_dt,
                stac_item_id=stac,
            )
        if i < 2:
            await _insert_cell_aggregates(
                session,
                block_id=block_a,
                product_id=product_id,
                scene_dt=scene_dt,
                stac_item_id=stac,
                cell_ids=cell_ids,
            )

    await _insert_job(
        session,
        subscription_id=subs[block_a],
        block_id=block_a,
        product_id=product_id,
        scene_id="S2A_OBS_A_FAIL",
        scene_dt=WINDOW_FROM + timedelta(days=10),
        status="failed",
        stac_item_id=None,
        valid_pct=None,
        error_code="provider_timeout",
    )
    await _insert_job(
        session,
        subscription_id=subs[block_a],
        block_id=block_a,
        product_id=product_id,
        scene_id="S2A_OBS_A_CLOUD",
        scene_dt=WINDOW_FROM + timedelta(days=12),
        status="skipped_cloud",
        stac_item_id=None,
        cloud=88.0,
        valid_pct=None,
    )

    # Block B — ungridded, 2 succeeded, both with aggregates.
    for i in range(2):
        scene_dt = WINDOW_FROM + timedelta(days=i * 3 + 1)
        stac = f"S2A_OBS_B_{i:02d}"
        await _insert_job(
            session,
            subscription_id=subs[block_b],
            block_id=block_b,
            product_id=product_id,
            scene_id=stac,
            scene_dt=scene_dt,
            status="succeeded",
            stac_item_id=stac,
            valid_pct=43.1,
        )
        await _insert_block_aggregates(
            session,
            block_id=block_b,
            product_id=product_id,
            scene_dt=scene_dt,
            stac_item_id=stac,
        )

    await session.commit()
    await session.execute(text("SET search_path TO public"))

    return Scenario(
        tenant_id=tenant.tenant_id,
        tenant_schema=tenant.schema_name,
        farm_id=farm_id,
        block_a=block_a,
        block_b=block_b,
        product_id=product_id,
    )


__all__ = [
    "INDEX_CODES",
    "WINDOW_FROM",
    "WINDOW_TO",
    "Decimal",
    "Scenario",
    "build_app",
    "make_context",
    "scenario",
]
