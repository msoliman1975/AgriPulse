"""Integration tests for the farm-wide **cell size** apply (PR 3).

The destructive half. Where PR 1's suite asserts that a threshold apply
never touches geometry, this one asserts the opposite operation behaves
safely: the confirmation is enforced server-side, history stays readable
across the cutover, and per-block tuning is not silently discarded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import build_app, make_context
from .test_grid_template import (
    _bootstrap,
    _make_farm_with_block,
    _s2_product_id,
    _seed_grid,
)

pytestmark = [pytest.mark.integration]


async def _configs(session: AsyncSession, *, schema: str, block_id: UUID) -> list[Any]:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    return list(
        (
            await session.execute(
                text(
                    "SELECT id, cell_size_m, anomaly_z_threshold, retired_at, "
                    "       effective_from, effective_to, superseded_at "
                    "FROM grid_configs WHERE block_id = :b ORDER BY created_at"
                ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
                {"b": block_id},
            )
        )
        .mappings()
        .all()
    )


async def _set_template(c: AsyncClient, farm_id: str, cell_size: float | None) -> None:
    r = await c.put(
        f"/api/v1/farms/{farm_id}/config/grid/template",
        json={"cell_size_m": cell_size, "anomaly_z_threshold": None},
    )
    assert r.status_code == 200, r.text


# ---- Preview ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_reports_a_rezone_and_demands_confirmation(
    admin_session: AsyncSession,
) -> None:
    tenant, context = await _bootstrap(admin_session, "cs-prev")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)

        r = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply-preview",
            json={"scope": "cell_size"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rezone_rows"] == 1
        assert body["changed_rows"] == 1
        assert body["requires_confirmation"] is True
        assert body["rows"][0]["action"] == "rezone"
        assert body["rows"][0]["target_cell_size_m"] == 20


@pytest.mark.asyncio
async def test_preview_blocks_a_size_the_product_cannot_take(
    admin_session: AsyncSession,
) -> None:
    """25 m on a 10 m source fails the integer-multiple rule.

    The original UX mock showed this as valid, which is why the preview
    runs the real backend guardrail per (block, product).
    """
    tenant, context = await _bootstrap(admin_session, "cs-blocked")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 25)

        body = (
            await c.post(
                f"/api/v1/farms/{farm_id}/config/grid/apply-preview",
                json={"scope": "cell_size"},
            )
        ).json()
        assert body["blocked_rows"] == 1
        assert body["changed_rows"] == 0
        assert body["is_noop"] is True
        # A refusal is not a rezone, so no confirmation is demanded.
        assert body["requires_confirmation"] is False
        assert "integer multiple" in body["rows"][0]["reason"]


@pytest.mark.asyncio
async def test_first_grid_is_a_create_and_needs_no_confirmation(
    admin_session: AsyncSession,
) -> None:
    """Gridding a farm for the first time destroys nothing.

    Demanding the destructive confirmation here would teach operators to
    type past it, which is how the confirmation stops working.
    """
    tenant, context = await _bootstrap(admin_session, "cs-create")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await admin_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )
        await admin_session.execute(
            text(
                "INSERT INTO imagery_aoi_subscriptions (block_id, product_id, is_active) "
                "VALUES (:b, :p, TRUE)"
            ).bindparams(
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"b": UUID(block_id), "p": product_id},
        )
        await admin_session.commit()
        await _set_template(c, farm_id, 20)

        body = (
            await c.post(
                f"/api/v1/farms/{farm_id}/config/grid/apply-preview",
                json={"scope": "cell_size"},
            )
        ).json()
        assert body["create_rows"] == 1
        assert body["rezone_rows"] == 0
        assert body["requires_confirmation"] is False

        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply", json={"scope": "cell_size"}
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["blocks_touched"] == 1


# ---- Confirmation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_rezone_without_confirmation_is_refused(admin_session: AsyncSession) -> None:
    """Enforced server-side, so a client that skips the dialog can't rezone."""
    tenant, context = await _bootstrap(admin_session, "cs-noconfirm")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)

        r = await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply", json={"scope": "cell_size"})
        assert r.status_code == 409, r.text

        wrong = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "not the farm"},
        )
        assert wrong.status_code == 409

        # Nothing was written by either attempt.
        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        assert len(rows) == 1
        assert float(rows[0]["cell_size_m"]) == 30.0


# ---- Apply -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_rezone_cuts_over_without_orphaning_history(
    admin_session: AsyncSession,
) -> None:
    """The whole point of gating this behind valid time.

    After the apply there are two configs: the old one still governing the
    scenes it produced, and the new one open-ended from the cutover. No
    gap, no overlap, and the old rows stay readable.
    """
    tenant, context = await _bootstrap(admin_session, "cs-cutover")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)

        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "F"},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["blocks_touched"] == 1

        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        assert len(rows) == 2
        old, new = rows
        assert float(old["cell_size_m"]) == 30.0
        assert float(new["cell_size_m"]) == 20.0
        assert old["effective_to"] is not None, "the replaced grid stops governing"
        assert old["retired_at"] == old["effective_to"]
        assert new["effective_from"] == old["effective_to"], "no gap, no overlap"
        assert new["effective_to"] is None
        assert new["superseded_at"] is None
        # Step 2 has not run — the old geometry is still live, not superseded.
        assert old["superseded_at"] is None


@pytest.mark.asyncio
async def test_rezone_preserves_each_blocks_tuned_threshold(
    admin_session: AsyncSession,
) -> None:
    """A bulk rezone must not quietly reset per-block sensitivity.

    ``upsert_config`` takes the threshold as a parameter, so passing None
    would wipe every block's tuning — invisible until alerts changed shape
    weeks later.
    """
    tenant, context = await _bootstrap(admin_session, "cs-keepz")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
            z="2.75",
        )
        await _set_template(c, farm_id, 20)

        r = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "F"},
        )
        assert r.status_code == 200, r.text

        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        new = rows[-1]
        assert new["anomaly_z_threshold"] is not None, "block tuning was discarded"
        assert float(new["anomaly_z_threshold"]) == 2.75


@pytest.mark.asyncio
async def test_matching_cell_size_is_a_reported_noop(admin_session: AsyncSession) -> None:
    """Zero-change must not silently look like success (#330)."""
    tenant, context = await _bootstrap(admin_session, "cs-noop")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="20.00",
        )
        await _set_template(c, farm_id, 20)

        body = (
            await c.post(
                f"/api/v1/farms/{farm_id}/config/grid/apply-preview",
                json={"scope": "cell_size"},
            )
        ).json()
        assert body["is_noop"] is True
        assert body["changed_rows"] == 0
        assert body["requires_confirmation"] is False

        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply", json={"scope": "cell_size"}
        )
        assert applied.status_code == 200
        assert applied.json()["blocks_touched"] == 0
        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        assert len(rows) == 1, "a no-op must not create a config"


@pytest.mark.asyncio
async def test_threshold_scope_still_never_rezones(admin_session: AsyncSession) -> None:
    """PR 1's safety property survives the new scope parameter.

    The template carries a *different* cell size, so a scope mix-up would
    show up here as a retired config.
    """
    tenant, context = await _bootstrap(admin_session, "cs-scopesafe")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
            z="1.50",
        )
        await c.put(
            f"/api/v1/farms/{farm_id}/config/grid/template",
            json={"cell_size_m": 20, "anomaly_z_threshold": 1.2},
        )

        r = await c.post(f"/api/v1/farms/{farm_id}/config/grid/apply", json={})
        assert r.status_code == 200

        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        assert len(rows) == 1, "threshold scope must never retire a config"
        assert float(rows[0]["cell_size_m"]) == 30.0
        assert float(rows[0]["anomaly_z_threshold"]) == 1.2


# ---- Authority -------------------------------------------------------------


def test_manage_config_and_subscription_manage_currently_coincide() -> None:
    """Documents why the extra capability check is not observable today.

    The apply endpoint requires ``imagery.subscription.manage`` on top of
    ``farm.manage_config`` for the destructive scope, because a rezone
    reshapes observation streams and spends heavy-worker time. As the
    matrix stands, every role granting the first also grants the second,
    so the check is defence-in-depth rather than a live distinction.

    If this test starts failing, someone has added a role that can edit
    farm config but not manage subscriptions — and for that role the
    cell-size scope will return 403 while the threshold scope keeps
    working. That is the intended behaviour; update this test rather than
    loosening the endpoint.
    """
    import pathlib

    import yaml

    spec = yaml.safe_load(
        (
            pathlib.Path(__file__).resolve().parents[3]
            / "app"
            / "shared"
            / "rbac"
            / "role_capabilities.yaml"
        ).read_text(encoding="utf-8")
    )
    roles = spec.get("roles", spec)
    manage_config = {
        n for n, s in roles.items() if "farm.manage_config" in ((s or {}).get("capabilities") or [])
    }
    sub_manage = {
        n
        for n, s in roles.items()
        if "imagery.subscription.manage" in ((s or {}).get("capabilities") or [])
    }
    assert manage_config, "expected at least one role to grant farm.manage_config"
    assert manage_config <= sub_manage, (
        "roles that can edit farm config but not manage subscriptions will get "
        f"403 on the cell-size scope: {sorted(manage_config - sub_manage)}"
    )


@pytest.mark.asyncio
async def test_cell_size_apply_is_denied_without_farm_config_authority(
    admin_session: AsyncSession,
) -> None:
    """A read-only farm role cannot rezone."""
    from app.shared.auth.context import FarmRole, FarmScope

    tenant, admin_ctx = await _bootstrap(admin_session, "cs-authz")
    app = build_app(admin_ctx, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)

    viewer = make_context(
        user_id=admin_ctx.user_id,
        tenant_id=admin_ctx.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.VIEWER),),
    )
    app2 = build_app(viewer, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as c2:
        denied = await c2.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "F"},
        )
        assert denied.status_code == 403, denied.text

        rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
        assert len(rows) == 1, "a denied request must not have rezoned"


# ---- Settle (rezone step 2) ------------------------------------------------


async def _seed_scene(
    session: AsyncSession,
    *,
    schema: str,
    config_id: UUID,
    block_id: UUID,
    product_id: UUID,
    at: datetime,
) -> None:
    """One NDVI observation on every cell of a config."""
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    cells = (
        await session.execute(
            text("SELECT id FROM grid_cells WHERE grid_config_id = :c").bindparams(
                bindparam("c", type_=PG_UUID(as_uuid=True))
            ),
            {"c": config_id},
        )
    ).all()
    for (cell_id,) in cells:
        await session.execute(
            text(
                "INSERT INTO block_grid_aggregates "
                "(time, cell_id, block_id, index_code, product_id, mean, "
                " valid_pixel_count, total_pixel_count, stac_item_id) "
                "VALUES (:t, :c, :b, 'ndvi', :p, 0.5, 100, 100, 'sc')"
            ).bindparams(
                bindparam("c", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"t": at, "c": cell_id, "b": block_id, "p": product_id},
        )
    await session.commit()


@pytest.mark.asyncio
async def test_settle_hands_history_over_once_the_backfill_lands(
    admin_session: AsyncSession,
) -> None:
    """Full settle: the new geometry covers everything, so the old is superseded."""
    from app.modules.grid.tasks import _settle_rezones_async

    tenant, context = await _bootstrap(admin_session, "cs-settle")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)
        await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "F"},
        )

    rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
    old, new = rows
    old_scene = datetime.now(UTC) - timedelta(days=10)

    # Nothing recomputed yet — settle must not move anything.
    await _settle_rezones_async(tenant.schema_name)
    after = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
    assert after[0]["superseded_at"] is None

    # Backfill lands: the new geometry now holds a scene older than
    # anything the old one had.
    await _seed_scene(
        admin_session,
        schema=tenant.schema_name,
        config_id=new["id"],
        block_id=UUID(block_id),
        product_id=product_id,
        at=old_scene,
    )
    result = await _settle_rezones_async(tenant.schema_name)
    assert result["settled_full"] == 1

    settled = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
    settled_old = next(r for r in settled if r["id"] == old["id"])
    settled_new = next(r for r in settled if r["id"] == new["id"])
    assert settled_old["superseded_at"] is not None, "old geometry governs nothing now"
    assert str(settled_new["effective_from"]).startswith(
        "0001-01-01"
    ), "the new geometry should extend back over all of history"


@pytest.mark.asyncio
async def test_partial_settle_leaves_two_geometries_and_says_so(
    admin_session: AsyncSession,
) -> None:
    """The honest case: the budget didn't reach everything.

    ``effective_from`` walks back only as far as was recomputed, and the
    old config keeps governing the rest rather than being superseded.
    """
    from app.modules.grid.tasks import _settle_rezones_async

    tenant, context = await _bootstrap(admin_session, "cs-partial")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        product_id = await _s2_product_id(admin_session)
        old_cfg = await _seed_grid(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=product_id,
            cell_size_m="30.00",
        )
        await _set_template(c, farm_id, 20)

    # The old geometry holds a very old scene...
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO grid_cells (grid_config_id, row_idx, col_idx, geom, centroid, area_m2) "
            "VALUES (:c, 0, 0, ST_GeomFromText("
            "'POLYGON((0 0,30 0,30 30,0 30,0 0))', 32636), "
            "ST_SetSRID(ST_Point(31.21, 30.001), 4326), 900)"
        ).bindparams(bindparam("c", type_=PG_UUID(as_uuid=True))),
        {"c": old_cfg},
    )
    await admin_session.commit()
    ancient = datetime.now(UTC) - timedelta(days=365)
    await _seed_scene(
        admin_session,
        schema=tenant.schema_name,
        config_id=old_cfg,
        block_id=UUID(block_id),
        product_id=product_id,
        at=ancient,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            f"/api/v1/farms/{farm_id}/config/grid/apply",
            json={"scope": "cell_size", "confirm_farm_name": "F"},
        )

    rows = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
    new = rows[-1]
    # ...but the backfill only reached a recent slice of it.
    recent = datetime.now(UTC) - timedelta(days=30)
    await _seed_scene(
        admin_session,
        schema=tenant.schema_name,
        config_id=new["id"],
        block_id=UUID(block_id),
        product_id=product_id,
        at=recent,
    )

    result = await _settle_rezones_async(tenant.schema_name)
    assert result["settled_partial"] == 1
    assert result["settled_full"] == 0

    settled = await _configs(admin_session, schema=tenant.schema_name, block_id=UUID(block_id))
    settled_old = next(r for r in settled if r["id"] == rows[0]["id"])
    settled_new = next(r for r in settled if r["id"] == new["id"])
    assert settled_old["superseded_at"] is None, "the old geometry still governs the tail"
    assert settled_old["effective_to"] == settled_new["effective_from"], "still no gap"
    assert (
        settled_new["effective_from"] < new["effective_from"]
    ), "effective_from should have walked backwards to the recomputed scene"
