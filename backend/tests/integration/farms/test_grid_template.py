"""Integration tests for the farm-level grid template (PR 1).

Scope is the **threshold** only — the farm template stores a cell size
but applying it would rezone, which waits on grid valid time. The most
important assertion in this file is therefore the negative one:
``test_apply_never_rezones``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [lon, lat],
                    [lon + side, lat],
                    [lon + side, lat + side],
                    [lon, lat + side],
                    [lon, lat],
                ]
            ]
        ],
    }


def _square_polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
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
            "name": "Test User",
        },
    )
    membership_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant_id},
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await session.commit()


async def _bootstrap(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


async def _s2_product_id(session: AsyncSession) -> UUID:
    """The catalog product seeded by public migration 0008."""
    row = (
        await session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a' LIMIT 1")
        )
    ).first()
    assert row is not None, "expected the seeded s2_l2a product"
    return UUID(str(row.id))


async def _seed_grid(
    session: AsyncSession,
    *,
    schema: str,
    block_id: UUID,
    product_id: UUID,
    cell_size_m: str = "20.00",
    z: str | None = None,
) -> UUID:
    """Give a block an active subscription + grid config, by SQL.

    Going through the real endpoints would need imagery ingestion; the
    template logic only cares that the rows exist.
    """
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO imagery_aoi_subscriptions (block_id, product_id, is_active) "
            "VALUES (:b, :p, TRUE)"
        ).bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {"b": block_id, "p": product_id},
    )
    config_id = (
        await session.execute(
            text(
                "INSERT INTO grid_configs "
                "(block_id, product_id, cell_size_m, utm_srid, anomaly_z_threshold) "
                "VALUES (:b, :p, CAST(:cs AS numeric), 32636, CAST(:z AS numeric)) "
                "RETURNING id"
            ).bindparams(
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"b": block_id, "p": product_id, "cs": cell_size_m, "z": z},
        )
    ).scalar_one()
    await session.commit()
    return UUID(str(config_id))


async def _read_config(session: AsyncSession, *, schema: str, config_id: UUID):
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    return (
        await session.execute(
            text(
                "SELECT id, cell_size_m, anomaly_z_threshold, retired_at "
                "FROM grid_configs WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": config_id},
        )
    ).first()


@pytest.fixture(autouse=True)
def _enable_feature_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FARM_CONFIG_TEMPLATE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _make_farm_with_block(c: AsyncClient) -> tuple[str, str]:
    farm = await c.post(
        "/api/v1/farms",
        json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
    )
    farm_id = farm.json()["id"]
    block = await c.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": "B1", "boundary": _square_polygon(31.21, 30.001)},
    )
    return farm_id, block.json()["id"]


# ---- Template round-trip ---------------------------------------------------


@pytest.mark.asyncio
async def test_template_round_trip(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "gt-round")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, _ = await _make_farm_with_block(c)

        empty = await c.get(f"/api/v1/farms/{farm_id}/config/grid/template")
        assert empty.status_code == 200
        assert empty.json() == {"cell_size_m": None, "anomaly_z_threshold": None}

        put = await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": 30.0, "anomaly_z_threshold": 1.2},
        )
        assert put.status_code == 200

        got = await c.get(f"/api/v1/farms/{farm_id}/config/grid/template")
        assert got.json() == {"cell_size_m": 30.0, "anomaly_z_threshold": 1.2}


@pytest.mark.asyncio
async def test_template_rejects_non_positive_values(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "gt-reject")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, _ = await _make_farm_with_block(c)
        bad = await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": 0, "anomaly_z_threshold": 1.2},
        )
        assert bad.status_code == 422


# ---- Preview ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_skips_blocks_without_a_grid(admin_session: AsyncSession) -> None:
    """A block with no subscription/grid is reported, not dropped."""
    _, context = await _bootstrap(admin_session, "gt-skip")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )

        preview = await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply-preview", json={})
        assert preview.status_code == 200
        body = preview.json()
        assert body["total_rows"] == 1
        assert body["skipped_rows"] == 1
        assert body["changed_rows"] == 0
        assert body["is_noop"] is True
        row = body["rows"][0]
        assert row["block_id"] == block_id
        assert row["action"] == "skipped"
        assert "subscription" in row["reason"].lower()


@pytest.mark.asyncio
async def test_preview_reports_a_threshold_change(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap(admin_session, "gt-change")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            z="1.50",
        )
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )

        body = (await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply-preview", json={})).json()
        assert body["changed_rows"] == 1
        assert body["is_noop"] is False
        row = body["rows"][0]
        assert row["action"] == "threshold"
        assert row["current_anomaly_z_threshold"] == 1.5
        assert row["target_anomaly_z_threshold"] == 1.2
        assert row["product_code"] == "s2_l2a"
        # Cell size travels as context so the UI can explain a skip.
        assert row["current_cell_size_m"] == 20.0


# ---- Apply -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_writes_the_threshold(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap(admin_session, "gt-apply")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        config_id = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            z="1.50",
        )
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )

        applied = await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply", json={})
        assert applied.status_code == 200
        assert applied.json()["blocks_touched"] == 1

        row = await _read_config(admin_session, schema=tenant.schema_name, config_id=config_id)
        assert float(row.anomaly_z_threshold) == 1.2


@pytest.mark.asyncio
async def test_apply_never_rezones(admin_session: AsyncSession) -> None:
    """The core safety property of PR 1.

    A threshold apply must leave the grid geometry completely alone: same
    config row (not a new one), same cell size, still active. If this ever
    routes through ``upsert_config`` the config would be retired and
    replaced whenever the template's cell size differed — turning a
    sensitivity tweak into a farm-wide rezone.
    """
    tenant, context = await _bootstrap(admin_session, "gt-norezone")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        config_id = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="20.00",
            z="1.50",
        )
        # Template cell size deliberately DIFFERS from the block's.
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": 40.0, "anomaly_z_threshold": 1.2},
        )

        await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply", json={})

        row = await _read_config(admin_session, schema=tenant.schema_name, config_id=config_id)
        assert row is not None
        assert row.retired_at is None, "apply must not retire the grid"
        assert float(row.cell_size_m) == 20.0, "apply must not change cell size"
        assert float(row.anomaly_z_threshold) == 1.2

        # And no second config was created for this (block, product).
        count = (
            await admin_session.execute(
                text("SELECT count(*) FROM grid_configs WHERE block_id = :b").bindparams(
                    bindparam("b", type_=PG_UUID(as_uuid=True))
                ),
                {"b": UUID(block_id)},
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_clear_override_restores_inheritance(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap(admin_session, "gt-clear")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        config_id = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            z="1.50",
        )
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )

        cleared = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"clear_override": True},
        )
        assert cleared.json()["blocks_touched"] == 1

        row = await _read_config(admin_session, schema=tenant.schema_name, config_id=config_id)
        assert row.anomaly_z_threshold is None, "clear_override must write NULL, not the template"


@pytest.mark.asyncio
async def test_apply_respects_block_ids_subset(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap(admin_session, "gt-subset")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        b1 = (
            await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B1", "boundary": _square_polygon(31.21, 30.001)},
            )
        ).json()["id"]
        b2 = (
            await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B2", "boundary": _square_polygon(31.213, 30.001)},
            )
        ).json()["id"]
        product_id = await _s2_product_id(admin_session)
        cfg1 = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(b1),
            product_id=product_id,
            z="1.50",
        )
        cfg2 = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(b2),
            product_id=product_id,
            z="1.50",
        )
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )

        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply", json={"block_ids": [b1]}
        )
        assert applied.json()["blocks_touched"] == 1

        r1 = await _read_config(admin_session, schema=tenant.schema_name, config_id=cfg1)
        r2 = await _read_config(admin_session, schema=tenant.schema_name, config_id=cfg2)
        assert float(r1.anomaly_z_threshold) == 1.2
        assert float(r2.anomaly_z_threshold) == 1.5, "unselected block must be untouched"


# ---- Lock ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grid_lock_blocks_block_level_config_write(
    admin_session: AsyncSession,
) -> None:
    """Locking the farm's grid category rejects the per-block PUT."""
    tenant, context = await _bootstrap(admin_session, "gt-lock")
    app = build_app(context, with_config=True, with_grid=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            z="1.20",
        )
        # Template matches the block, so locking is not divergent.
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": None, "anomaly_z_threshold": 1.2},
        )
        locked = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/lock",
            json={"force_overwrite": False},
        )
        assert locked.status_code == 200
        assert locked.json()["locked"] is True

        denied = await c.put(
            f"/api/v1/blocks/{block_id}/grid-configs/{product_id}",
            json={"cell_size_m": 40, "anomaly_z_threshold": 2.0},
        )
        assert denied.status_code == 409

        await c.post(f"/api/v1/farms/{farm_id}/config/grid/unlock", json={})
        # Unlocked again — the same write is now allowed through the guard.
        allowed = await c.put(
            f"/api/v1/blocks/{block_id}/grid-configs/{product_id}",
            json={"cell_size_m": 40, "anomaly_z_threshold": 2.0},
        )
        assert allowed.status_code != 409


@pytest.mark.asyncio
async def test_lock_state_includes_grid(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "gt-lockstate")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, _ = await _make_farm_with_block(c)
        locks = await c.get(f"/api/v1/farms/{farm_id}/config/locks")
        assert locks.status_code == 200
        assert locks.json()["grid"] is False
