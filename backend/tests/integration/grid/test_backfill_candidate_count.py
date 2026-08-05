"""The apply endpoint's queued-scene estimate must match the real fan-out.

Two failures live here, and the first one shipped:

* ``scenes_queued`` was derived from ``scenes_affected`` — the *destructive*
  cost, counted through the geometry a rezone replaces. A ``create`` has no
  prior geometry, so the count was structurally zero and a farm gridded for
  the first time reported "0 scenes queued" while the task it had just
  fired recomputed its whole imagery history.
* The estimate and the enumeration ask "is there a raw-bands asset?" in two
  languages — SQL and Python. They are pinned together here, because a
  hand-copied predicate drifting apart is what produced the first failure.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.grid.backfill import (
    count_farm_backfill_candidates,
    extract_raw_bands_key,
    list_backfill_jobs,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM_BOUNDARY = "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
_BLOCK_BOUNDARY = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"

# Every shape the extractor accepts, and every near-miss it rejects. The
# SQL mirror has to agree on all of them.
_MANIFESTS: tuple[tuple[str, Any, bool], ...] = (
    ("dict_s3_href", {"raw_bands": {"href": "s3://bucket/t/raw_bands.tif"}}, True),
    ("dict_https_href", {"raw_bands": {"href": "https://cdn/t/raw_bands.tif"}}, False),
    ("dict_no_raw_bands", {"ndvi": {"href": "s3://bucket/t/ndvi.tif"}}, False),
    ("dict_raw_bands_not_object", {"raw_bands": "s3://bucket/t/raw_bands.tif"}, False),
    ("dict_raw_bands_no_href", {"raw_bands": {"size": 12}}, False),
    ("list_with_raw_bands", ["/t/ndvi.tif", "/t/raw_bands.tif"], True),
    ("list_without_raw_bands", ["/t/ndvi.tif"], False),
    ("empty_list", [], False),
    ("empty_dict", {}, False),
    ("null_manifest", None, False),
)


@pytest.fixture
async def farm_env(admin_session: Any) -> dict[str, Any]:
    """A tenant with one gridded block, ready to accept ingestion jobs."""
    slug = f"bfc-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'BF', 'BF', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM_BOUNDARY},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :fid, 'BB', 'BB', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id), "b": _BLOCK_BOUNDARY},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    # A live grid — `count_farm_backfill_candidates` keys on the farm's
    # live grids, exactly as the backfill task's fan-out does.
    await admin_session.execute(
        text(
            "INSERT INTO grid_configs (id, block_id, product_id, cell_size_m) "
            "VALUES (:id, :b, :p, 30)"
        ),
        {"id": str(uuid4()), "b": str(block_id), "p": str(product_id)},
    )
    await admin_session.commit()
    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_id": block_id,
        "product_id": product_id,
    }


async def _add_job(
    session: Any,
    env: dict[str, Any],
    *,
    assets: Any,
    status: str = "succeeded",
    stac_item_id: str | None = "item",
    scene_datetime: datetime | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO imagery_ingestion_jobs "
            "  (id, block_id, product_id, scene_datetime, status, stac_item_id, assets_written) "
            "VALUES (:id, :b, :p, :dt, :st, :item, CAST(:assets AS jsonb))"
        ),
        {
            "id": str(uuid4()),
            "b": str(env["block_id"]),
            "p": str(env["product_id"]),
            "dt": scene_datetime or datetime.now(UTC),
            "st": status,
            "item": stac_item_id,
            "assets": None if assets is None else json.dumps(assets),
        },
    )


async def test_sql_predicate_matches_the_python_extractor(
    admin_session: Any, farm_env: dict[str, Any]
) -> None:
    """The lock-step guard: both languages agree on every manifest shape."""
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    base = datetime.now(UTC)
    for i, (_name, assets, _expected) in enumerate(_MANIFESTS):
        await _add_job(
            admin_session, farm_env, assets=assets, scene_datetime=base - timedelta(days=i)
        )
    await admin_session.commit()

    expected = sum(1 for _n, assets, ok in _MANIFESTS if ok)
    # Sanity: the fixtures actually exercise both branches.
    assert 0 < expected < len(_MANIFESTS)
    # And the Python extractor agrees with the table's own `expected` flags.
    assert [extract_raw_bands_key(a) is not None for _n, a, _ok in _MANIFESTS] == [
        ok for _n, _a, ok in _MANIFESTS
    ]

    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    counted = await count_farm_backfill_candidates(
        admin_session, farm_id=farm_env["farm_id"], since=None, per_pair_cap=1000
    )
    enumerated = await list_backfill_jobs(
        admin_session,
        block_id=farm_env["block_id"],
        product_id=farm_env["product_id"],
        since=None,
        limit=1000,
    )
    assert counted == expected
    assert len(enumerated) == expected


async def test_a_first_time_grid_reports_the_work_it_queued(
    admin_session: Any, farm_env: dict[str, Any]
) -> None:
    """The shipped bug: a create has no prior geometry, so the old count
    (through ``grid_cells``) was zero while real work was enqueued."""
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    base = datetime.now(UTC)
    for i in range(7):
        await _add_job(
            admin_session,
            farm_env,
            assets={"raw_bands": {"href": f"s3://b/{i}/raw_bands.tif"}},
            scene_datetime=base - timedelta(days=i),
        )
    await admin_session.commit()

    # No cells and no aggregates exist — this block has never been gridded
    # before, which is precisely the state that used to report 0.
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    cells = (await admin_session.execute(text("SELECT count(*) FROM grid_cells"))).scalar_one()
    assert cells == 0

    counted = await count_farm_backfill_candidates(
        admin_session, farm_id=farm_env["farm_id"], since=None, per_pair_cap=1000
    )
    assert counted == 7


async def test_only_succeeded_jobs_with_a_stac_item_count(
    admin_session: Any, farm_env: dict[str, Any]
) -> None:
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    good = {"raw_bands": {"href": "s3://b/x/raw_bands.tif"}}
    base = datetime.now(UTC)
    await _add_job(admin_session, farm_env, assets=good, scene_datetime=base)
    await _add_job(
        admin_session,
        farm_env,
        assets=good,
        status="running",
        scene_datetime=base - timedelta(days=1),
    )
    await _add_job(
        admin_session,
        farm_env,
        assets=good,
        stac_item_id=None,
        scene_datetime=base - timedelta(days=2),
    )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    counted = await count_farm_backfill_candidates(
        admin_session, farm_id=farm_env["farm_id"], since=None, per_pair_cap=1000
    )
    assert counted == 1


async def test_per_pair_cap_bounds_the_count_like_the_fan_out(
    admin_session: Any, farm_env: dict[str, Any]
) -> None:
    """The estimate must be capped identically to the enumeration, or a
    deep-history farm would report more than the backfill will ever run."""
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    base = datetime.now(UTC)
    for i in range(9):
        await _add_job(
            admin_session,
            farm_env,
            assets={"raw_bands": {"href": f"s3://b/{i}/raw_bands.tif"}},
            scene_datetime=base - timedelta(days=i),
        )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    assert (
        await count_farm_backfill_candidates(
            admin_session, farm_id=farm_env["farm_id"], since=None, per_pair_cap=4
        )
        == 4
    )
    assert (
        len(
            await list_backfill_jobs(
                admin_session,
                block_id=farm_env["block_id"],
                product_id=farm_env["product_id"],
                since=None,
                limit=4,
            )
        )
        == 4
    )


async def test_a_retired_grid_is_not_counted(admin_session: Any, farm_env: dict[str, Any]) -> None:
    """The fan-out walks live grids only; the estimate must do the same."""
    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    await _add_job(
        admin_session, farm_env, assets={"raw_bands": {"href": "s3://b/x/raw_bands.tif"}}
    )
    await admin_session.execute(text("UPDATE grid_configs SET retired_at = now()"))
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{farm_env["schema"]}", public'))
    counted = await count_farm_backfill_candidates(
        admin_session, farm_id=farm_env["farm_id"], since=None, per_pair_cap=1000
    )
    assert counted == 0
