"""A beta dry run folds one block cell by cell and writes nothing.

Two claims, and neither can be checked without a real database.

**It fans out per cell.** A cell-scoped tree is not previewed by one
block-level walk: that is a different evaluation that happens to use the same
tree. The dry run has to swap each cell's imagery means into the block
context the way the sweep does, and the only way to see that it did is to
give two cells different readings and get two different answers back.

**It writes nothing.** Not a recommendation, not an alert, not a verdict, not
a trace row. An author folds the canvas as often as they like. The test
counts every one of those tables before and after rather than trusting the
absence of an INSERT in the code.

One tenant schema for the module: creating a tenant replays every tenant
migration, and a schema per test is what pushed this job past its budget
once already.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.recommendations.folding_authoring import FoldingTreeAuthorService
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"
_CELL_POLY = "POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))"

# Two cells is the smallest number that can disagree. One cell reads above
# the floor and one below, so a run that ignored the per-cell means would
# return two identical answers and this test would say so.
_HIGH = Decimal("0.80")
_LOW = Decimal("0.10")
_FLOOR = 0.30

# Every table a write would land in. Counted before and after the run.
_WRITE_TABLES = (
    "recommendations",
    "recommendations_history",
    "alerts",
    "decision_tree_block_verdicts",
    "decision_tree_eval_traces",
)


def _definition(code: str) -> dict[str, Any]:
    """A cell-scoped tree whose only decision is the cell's own NDVI.

    No `register` node, so the fold produces no card for any cell. That is
    deliberate: the finding catalogue lands in a separate change, and a dry
    run must still work — and still say something true — without it. What is
    being checked here is the fan-out and the write-free guarantee, and both
    are visible in the per-cell walk regardless of whether a card comes out.
    """
    return {
        "code": code,
        "name_en": "Dry run tree",
        "name_ar": "شجرة تجربة",
        "scope": "cell",
        "parameters": {"floor": {"type": "number", "default": _FLOOR, "min": -1.0, "max": 1.0}},
        "root": "n_switch",
        "nodes": {
            "n_switch": {
                "label_en": "Is the canopy above the floor?",
                "switch": {
                    "on": {"source": "indices", "index": "ndvi", "field": "mean"},
                    "cases": [
                        {"ge": {"source": "params", "name": "floor"}, "go": "n_ok"},
                    ],
                    "default": "n_low",
                },
            },
            "n_ok": {
                "label_en": "Above the floor",
                "set": {"verdict": "ok"},
                "next": "n_stop_ok",
            },
            "n_low": {
                "label_en": "Below the floor",
                "set": {"verdict": "low"},
                "next": "n_stop_low",
            },
            # Two stop nodes rather than one, so which branch a cell took is
            # visible in the report. Without that, a run that ignored the
            # per-cell means would return two identical rows and the fan-out
            # assertion would pass on nothing.
            "n_stop_ok": {"label_en": "End of the walk, healthy", "stop": True},
            "n_stop_low": {"label_en": "End of the walk, low", "stop": True},
        },
    }


async def _seed(admin_session: Any) -> dict[str, Any]:
    """One farm, one block, two grid cells with different NDVI means."""
    if not _SHARED:
        slug = f"betadr-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

        farm_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO farms (
                        code, name, country_code, boundary, boundary_utm,
                        centroid, area_m2
                    ) VALUES (
                        'BDR-FARM', 'Beta dry run farm', 'EG',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                        100000
                    ) RETURNING id
                    """
                ),
                {"poly": _POLY},
            )
        ).scalar_one()

        block_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO blocks (
                        farm_id, code, boundary, boundary_utm, centroid,
                        area_m2, aoi_hash
                    ) VALUES (
                        :farm_id, 'BDR-01',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                        100000, 'bdr-hash'
                    ) RETURNING id
                    """
                ),
                {"farm_id": farm_id, "poly": _POLY},
            )
        ).scalar_one()

        product_id = uuid4()
        grid_config_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO grid_configs (block_id, product_id, cell_size_m, utm_srid)
                    VALUES (:block_id, :product_id, 20, 32636)
                    RETURNING id
                    """
                ),
                {"block_id": block_id, "product_id": product_id},
            )
        ).scalar_one()

        cells = [
            (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO grid_cells (
                            grid_config_id, row_idx, col_idx, geom, centroid, area_m2
                        ) VALUES (
                            :cfg, :row, 1,
                            ST_GeomFromText(:cell_poly, 4326),
                            ST_SetSRID(ST_MakePoint(31.205, 30.005), 4326),
                            400
                        ) RETURNING id
                        """
                    ),
                    {"cfg": grid_config_id, "row": idx, "cell_poly": _CELL_POLY},
                )
            ).scalar_one()
            for idx in range(2)
        ]

        observed = datetime.now(UTC) - timedelta(days=1)
        # The block-level mean sits above the floor. If a cell's own mean
        # were ignored, both cells would take the `n_ok` branch and the
        # fan-out assertion below would fail rather than pass by accident.
        await admin_session.execute(
            text(
                """
                INSERT INTO block_index_aggregates
                    (time, block_id, index_code, product_id, mean,
                     valid_pixel_count, total_pixel_count, stac_item_id)
                VALUES (:t, :b, 'ndvi', :p, :m, 100, 100, 'bdr-scene')
                """
            ),
            {"t": observed, "b": block_id, "p": product_id, "m": _HIGH},
        )
        for cell_id, mean in zip(cells, (_HIGH, _LOW), strict=True):
            await admin_session.execute(
                text(
                    """
                    INSERT INTO block_grid_aggregates
                        (time, cell_id, block_id, index_code, product_id, mean,
                         valid_pixel_count, total_pixel_count, stac_item_id)
                    VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, 'bdr-scene')
                    """
                ),
                {"t": observed, "c": cell_id, "b": block_id, "p": product_id, "m": mean},
            )

        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            tenant_id=tenant.tenant_id,
            farm_id=farm_id,
            block_id=block_id,
            cells=cells,
        )

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return _SHARED


async def _counts(session: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in _WRITE_TABLES:
        out[table] = (
            await session.execute(text(f"SELECT count(*) AS n FROM {table}"))
        ).scalar_one()
    return out


@pytest.mark.asyncio
async def test_dry_run_folds_every_cell_and_writes_nothing(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    service = FoldingTreeAuthorService(public_session=admin_session, tenant_id=seeded["tenant_id"])
    code = f"beta_dryrun_{uuid4().hex[:8]}"
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))

    before = await _counts(admin_session)
    report = await service.dry_run(
        tree_id=tree["id"],
        block_id=seeded["block_id"],
        definition=None,
        version_id=None,
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    after = await _counts(admin_session)

    assert report["cells_evaluated"] == 2
    assert report["scope"] == "cell"
    assert report["code"] == code
    assert report["cells_errored"] == 0

    # No register nodes, so no cell produces a card. A healthy cell is an
    # answer, not a missing one, and it is still reported.
    assert report["cells_carded"] == 0
    assert all(cell["identity"] == [] for cell in report["cells"])

    # The fan-out. One cell took `n_ok` and one took `n_low`, which can only
    # happen if each walk saw that cell's own mean.
    stopped = sorted(cell["stopped_at"] for cell in report["cells"])
    assert stopped == [
        "n_stop_low",
        "n_stop_ok",
    ], "both cells took the same branch, so the per-cell means were ignored"
    assert before == after, f"the dry run wrote rows: {before} -> {after}"


@pytest.mark.asyncio
async def test_dry_run_prefers_the_definition_it_is_handed(admin_session: Any) -> None:
    """The designer folds what is on screen, without saving first.

    Compiled the same way a save compiles it, so a body the dry run accepts
    is a body that saves.
    """
    seeded = await _seed(admin_session)
    service = FoldingTreeAuthorService(public_session=admin_session, tenant_id=seeded["tenant_id"])
    code = f"beta_unsaved_{uuid4().hex[:8]}"
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))

    unsaved = _definition(code)
    unsaved["nodes"]["n_stop_ok"]["label_en"] = "A different end, never saved"

    report = await service.dry_run(
        tree_id=tree["id"],
        block_id=seeded["block_id"],
        definition=unsaved,
        version_id=None,
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    assert report["cells_evaluated"] == 2
    # A handed-in definition belongs to no version, so the report says so
    # rather than naming a version that did not produce it.
    assert report["version_id"] is None

    # And the unsaved body was not stored on the way through.
    stored = await service.get_tree(tree["id"])
    assert len(stored["versions"]) == 1
    assert stored["definition"]["nodes"]["n_stop_ok"]["label_en"] == "End of the walk, healthy"


@pytest.mark.asyncio
async def test_dry_run_reports_targeting_without_enforcing_it(admin_session: Any) -> None:
    """A tree the sweep would skip must not look like one that runs.

    The block picker filters to targeted blocks, so the designer cannot
    reach this case — but an API caller can, and "works in the dry run, does
    nothing in production" is the gap this endpoint closes.
    """
    seeded = await _seed(admin_session)
    service = FoldingTreeAuthorService(public_session=admin_session, tenant_id=seeded["tenant_id"])
    code = f"beta_target_{uuid4().hex[:8]}"
    definition = _definition(code)
    definition["crop_paths"] = ["date_palm"]
    tree = await service.create_tree(
        code=code, definition=definition, notes=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))

    report = await service.dry_run(
        tree_id=tree["id"],
        block_id=seeded["block_id"],
        definition=None,
        version_id=None,
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    assert report["targeting"]["matched"] is False
    assert report["targeting"]["axis"] == "crop"
    assert report["cells_evaluated"] == 2, "evaluated anyway, so the author can see it"


@pytest.mark.asyncio
async def test_dry_run_on_a_block_with_no_grid_returns_no_cells(admin_session: Any) -> None:
    """The honest answer for an ungridded block.

    A cell-scoped tree does not fire there in the sweep either, so an empty
    report is the truth and not a failure.
    """
    seeded = await _seed(admin_session)
    ungridded = (
        await admin_session.execute(
            text(
                """
                INSERT INTO blocks (
                    farm_id, code, boundary, boundary_utm, centroid, area_m2, aoi_hash
                ) VALUES (
                    :farm_id, :code,
                    ST_GeomFromText(:poly, 4326),
                    ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                    ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                    100000, :hash
                ) RETURNING id
                """
            ),
            {
                "farm_id": seeded["farm_id"],
                "code": f"BDR-{uuid4().hex[:4]}",
                "poly": _POLY,
                "hash": uuid4().hex,
            },
        )
    ).scalar_one()
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))

    service = FoldingTreeAuthorService(public_session=admin_session, tenant_id=seeded["tenant_id"])
    code = f"beta_nogrid_{uuid4().hex[:8]}"
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))

    report = await service.dry_run(
        tree_id=tree["id"],
        block_id=UUID(str(ungridded)),
        definition=None,
        version_id=None,
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    assert report["cells_evaluated"] == 0
    assert report["cells"] == []
