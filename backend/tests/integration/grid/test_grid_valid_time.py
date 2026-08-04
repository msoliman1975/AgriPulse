"""Valid-time invariants on ``grid_configs`` (tenant migration 0054).

The §2.2 regression guard lives in ``test_rezone_orphans_history.py`` — it
asserts the *behaviour* users see. This file asserts the *schema contract*
that behaviour rests on, so a future change that quietly drops the exclusion
constraint or mis-stamps a range fails here rather than as a mysterious
heatmap bug months later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.grid.repository import GridRepository
from app.modules.grid.service import get_grid_service
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM_BOUNDARY = "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
_BLOCK_BOUNDARY = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"


@pytest.fixture
async def block_env(admin_session: Any) -> dict[str, Any]:
    """A tenant with one un-gridded block."""
    slug = f"gvt2-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'VT', 'VT', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM_BOUNDARY},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :fid, 'VB', 'VB', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id), "b": _BLOCK_BOUNDARY},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    await admin_session.commit()
    return {"schema": schema, "block_id": block_id, "product_id": product_id}


async def _configs(session: Any, env: dict[str, Any]) -> list[dict[str, Any]]:
    await session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    rows = (
        (
            await session.execute(
                text(
                    "SELECT cell_size_m, retired_at, effective_from, effective_to, "
                    "       superseded_at "
                    "FROM grid_configs WHERE block_id = :b ORDER BY created_at"
                ),
                {"b": str(env["block_id"])},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def test_first_grid_governs_all_of_history(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """A block's first grid claims ``-infinity``.

    Anything else would silently strand a historical backfill: the scenes
    predate the config row, so a `now()` lower bound would leave them with
    no governing geometry at all.
    """
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    configs = await _configs(admin_session, block_env)
    assert len(configs) == 1
    assert configs[0]["effective_to"] is None

    # Asserted behaviourally rather than by comparing the stored literal:
    # asyncpg deserialises `-infinity` as a tz-naive `datetime.min`, so an
    # equality check here would be testing the driver's representation
    # instead of the property that matters — that a decade-old scene has a
    # geometry to be gridded against.
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    repo = GridRepository(admin_session)
    ancient = await repo.list_cells_for_scene(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    assert ancient, "the first grid must govern scenes that predate its own row"


async def test_rezone_splits_the_timeline_without_gap_or_overlap(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """The cutover: old range closes exactly where the new one opens.

    A gap would leave scenes in the seam ungoverned and unreadable; an
    overlap would make "which geometry describes this scene" ambiguous and
    is rejected outright by the exclusion constraint.
    """
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    for size in ("20", "40"):
        await service.upsert_config(
            block_id=block_env["block_id"],
            product_id=block_env["product_id"],
            cell_size_m=Decimal(size),
            created_by=None,
        )
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))

    configs = await _configs(admin_session, block_env)
    assert len(configs) == 2
    old, new = configs

    assert old["effective_to"] is not None, "the replaced grid must stop governing"
    assert (
        old["retired_at"] == old["effective_to"]
    ), "transaction time and valid time are stamped together at the cutover"
    assert new["effective_from"] == old["effective_to"], "no gap, no overlap"
    assert new["effective_to"] is None, "the live grid is open-ended"
    assert new["retired_at"] is None


async def test_overlapping_ranges_are_rejected(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """The exclusion constraint is the real guard, not application code.

    Two geometries governing the same scene time for one (block, product)
    would make every read non-deterministic. This must fail in the
    database, so no code path — including a future bulk apply — can
    produce it.

    The inserted row carries ``retired_at`` deliberately. The pre-existing
    partial unique index only covers non-retired rows, so without that the
    older "one active config" guard fires first and this test would pass
    without the exclusion constraint existing at all. Retired configs are
    exactly the ones the unique index does *not* protect, and exactly the
    ones valid time makes readable again — so they are where overlap has
    to be caught.
    """
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    # The existing config is [-infinity, NULL). A retired row covering any
    # part of that span is invisible to the unique index but still overlaps.
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        await admin_session.execute(
            text(
                "INSERT INTO grid_configs "
                "(block_id, product_id, cell_size_m, utm_srid, "
                " effective_from, effective_to, retired_at) "
                "VALUES (:b, :p, 40, 32636, '-infinity'::timestamptz, :t, :t)"
            ),
            {
                "b": str(block_env["block_id"]),
                "p": str(block_env["product_id"]),
                "t": datetime.now(UTC),
            },
        )
    assert "ex_grid_configs_no_overlap" in str(excinfo.value)
    await admin_session.rollback()


async def test_superseded_configs_do_not_block_their_replacement(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """A superseded config governs nothing, so it must not occupy its range.

    This is what makes "rewrite history" expressible: the replacement
    claims `-infinity`, which would collide with the config it replaced if
    superseded rows still participated in the constraint.
    """
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    await admin_session.execute(
        text(
            "UPDATE grid_configs SET superseded_at = now(), retired_at = now() "
            "WHERE block_id = :b"
        ),
        {"b": str(block_env["block_id"])},
    )
    # Now a replacement claiming the whole timeline is accepted.
    await admin_session.execute(
        text(
            "INSERT INTO grid_configs "
            "(block_id, product_id, cell_size_m, utm_srid, effective_from) "
            "VALUES (:b, :p, 40, 32636, '-infinity'::timestamptz)"
        ),
        {"b": str(block_env["block_id"]), "p": str(block_env["product_id"])},
    )
    await admin_session.commit()

    configs = await _configs(admin_session, block_env)
    assert len(configs) == 2
    assert sum(1 for c in configs if c["superseded_at"] is not None) == 1


async def test_effective_range_must_not_invert(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """`effective_to <= effective_from` is meaningless and rejected."""
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    now = datetime.now(UTC)
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        await admin_session.execute(
            text(
                "INSERT INTO grid_configs "
                "(block_id, product_id, cell_size_m, utm_srid, "
                " effective_from, effective_to) "
                "VALUES (:b, :p, 20, 32636, :f, :t)"
            ),
            {
                "b": str(block_env["block_id"]),
                "p": str(block_env["product_id"]),
                "f": now,
                "t": now - timedelta(days=1),
            },
        )
    assert "ck_grid_configs_effective_range" in str(excinfo.value)
    await admin_session.rollback()


async def test_write_path_grids_a_scene_on_its_own_geometry(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """`list_cells_for_scene` is the A3 write-path fix.

    A backfilled or late-arriving scene that predates a rezone must be
    computed against the geometry that governs *its* time. Using the live
    grid instead writes rows that no valid-time-aware read can return —
    silent, and only visible later as missing history.
    """
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    old_scene = datetime.now(UTC) - timedelta(days=30)

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("40"),
        created_by=None,
    )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    repo = GridRepository(admin_session)

    historical = await repo.list_cells_for_scene(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        at=old_scene,
    )
    current = await repo.list_cells_for_scene(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        at=datetime.now(UTC),
    )
    assert historical, "a pre-rezone scene still has a governing geometry"
    assert current, "a present-day scene lands on the live geometry"
    assert {c["cell_id"] for c in historical}.isdisjoint(
        {c["cell_id"] for c in current}
    ), "the two scene times must resolve to different grids"
    # 20 m cells over the same block are finer, so there are more of them.
    assert len(historical) > len(current)


async def test_cleanup_drops_only_superseded_rows(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """The cleanup task reclaims superseded geometries and nothing else.

    The dangerous failure mode here is over-deletion: a retired-but-still-
    governing config holds the only readable copy of its period's history
    (that is the whole point of valid time), so dropping it would recreate
    §2.2 with data loss instead of just unreadability.
    """
    from app.modules.grid.tasks import _cleanup_superseded_async

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    for size in ("20", "40"):
        await service.upsert_config(
            block_id=block_env["block_id"],
            product_id=block_env["product_id"],
            cell_size_m=Decimal(size),
            created_by=None,
        )
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))

    before = await _configs(admin_session, block_env)
    assert len(before) == 2

    # Retired but NOT superseded — it still governs its own period.
    #
    # Assertions are scoped to this tenant's configs rather than the task's
    # return counters: the sweep is deliberately multi-tenant, so other
    # tests' tenants contribute to those totals.
    result = await _cleanup_superseded_async(retention_days=0, max_configs_per_tenant=10)
    assert result["tenants_failed"] == 0
    after_retired = await _configs(admin_session, block_env)
    assert len(after_retired) == 2, "a retired config still governs history — keep it"

    # Now supersede it, as the rezone's step 2 would once a backfill has
    # regenerated those scenes under the new geometry.
    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    await admin_session.execute(
        text(
            "UPDATE grid_configs SET superseded_at = now() - interval '1 day' "
            "WHERE block_id = :b AND retired_at IS NOT NULL"
        ),
        {"b": str(block_env["block_id"])},
    )
    await admin_session.commit()

    result = await _cleanup_superseded_async(retention_days=0, max_configs_per_tenant=10)
    assert result["tenants_failed"] == 0
    assert result["configs_dropped"] >= 1

    remaining = await _configs(admin_session, block_env)
    assert len(remaining) == 1
    assert remaining[0]["superseded_at"] is None
    assert remaining[0]["retired_at"] is None, "the live geometry survives"


async def test_cleanup_respects_the_retention_delay(
    admin_session: Any, block_env: dict[str, Any]
) -> None:
    """A freshly superseded config is kept, so a mistaken rezone is recoverable."""
    from app.modules.grid.tasks import _cleanup_superseded_async

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_env["block_id"],
        product_id=block_env["product_id"],
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{block_env["schema"]}", public'))
    await admin_session.execute(
        text(
            "UPDATE grid_configs SET superseded_at = now(), retired_at = now() "
            "WHERE block_id = :b"
        ),
        {"b": str(block_env["block_id"])},
    )
    await admin_session.commit()

    result = await _cleanup_superseded_async(retention_days=7, max_configs_per_tenant=10)
    assert result["tenants_failed"] == 0
    assert len(await _configs(admin_session, block_env)) == 1
