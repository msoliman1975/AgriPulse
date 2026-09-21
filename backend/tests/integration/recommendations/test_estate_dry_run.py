"""The estate dry run folds a whole tenant and writes no card.

Three claims, and none of them can be checked without a database.

**It writes nothing but its own report row.** Not a recommendation, not an
alert, not a verdict, not an evaluation trace. Stage B points this run at a
live tenant before anyone has agreed to switch the tree on, so "writes
nothing" is the contract that makes it safe. The test counts every table a
write would land in, before and after, rather than trusting that no INSERT
appears in the code.

**It covers every active block, not one.** Two blocks are seeded, each with
two cells, and the report has to count four cells. A run that folded the first
block only would still return a plausible report.

**The report is the one in design section 9.** The finding-set table, the
rules fired out of rules defined, the composed share and the error count are
asserted against a tree whose answer is known in advance.

One tenant schema for the module: creating a tenant replays every tenant
migration, and a schema per test is what pushed this job past its budget once
already.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.recommendations.folding_authoring import FoldingTreeAuthorService
from app.modules.recommendations.folding_report import (
    EstateDryRunRepository,
    EstateDryRunService,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"
_CELL_POLY = "POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))"

# One cell reads above the floor and one below, in each of two blocks. So the
# known answer is: four cells, two healthy, two carrying {ndvi_low}.
_HIGH = Decimal("0.80")
_LOW = Decimal("0.10")
_FLOOR = 0.30

# Every table a write would land in. `decision_tree_estate_dry_runs` is not
# here on purpose: the report row is the one write this run is allowed.
_WRITE_TABLES = (
    "recommendations",
    "recommendations_history",
    "alerts",
    "decision_tree_block_verdicts",
    "decision_tree_eval_traces",
    "decision_tree_eval_runs",
)


def _definition(code: str) -> dict[str, Any]:
    """A cell-scoped tree that registers one finding and stops.

    ``ndvi_low`` is a platform catalogue code seeded by public migration 0090,
    so the compiler's check against the catalogue passes and the fold has a
    clause to read. The combination rule on ``{ndvi_low}`` fires; the rule on
    ``{ndvi_low, dry}`` cannot, because no node registers ``dry`` — which is
    what makes "rules fired, 1 of 2" a real assertion rather than arithmetic.

    Both rules carry a ``code``. The compiler drops it, so the report names
    them by their set; the assertions below say so rather than hiding it.
    """
    return {
        "code": code,
        "name_en": "Estate dry run tree",
        "name_ar": "شجرة تجربة المزرعة",
        "scope": "cell",
        "parameters": {"floor": {"type": "number", "default": _FLOOR, "min": -1.0, "max": 1.0}},
        "root": "n_switch",
        "registers": ["ndvi_low", "dry"],
        "combinations": [
            {
                "code": "r_low",
                "codes": ["ndvi_low"],
                "text_en": "Vigour is below the band. Check water first.",
                "text_ar": "الحيوية دون النطاق. افحص الري أولا.",
                "action_type": "irrigate",
            },
            {
                "code": "r_never",
                "codes": ["ndvi_low", "dry"],
                "text_en": "Water shortage is the cause.",
                "text_ar": "نقص الماء هو السبب.",
                "action_type": "irrigate",
            },
        ],
        "nodes": {
            "n_switch": {
                "label_en": "Is the canopy above the floor?",
                "switch": {
                    "on": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                    "cases": [
                        {"ge": {"source": "params", "name": "floor"}, "go": "n_stop_ok"},
                    ],
                    "default": "n_low",
                },
            },
            "n_low": {
                "label_en": "Below the floor",
                "register": {"code": "ndvi_low", "severity": "warning"},
                "next": "n_stop_low",
            },
            "n_stop_ok": {"label_en": "End of the walk, healthy", "stop": True},
            "n_stop_low": {"label_en": "End of the walk, low", "stop": True},
        },
    }


async def _seed_block(session: Any, *, farm_id: Any, code: str) -> Any:
    """One block with a two-cell grid, one cell high and one low."""
    block_id = (
        await session.execute(
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
            {"farm_id": farm_id, "code": code, "poly": _POLY, "hash": f"edr-{code}"},
        )
    ).scalar_one()

    product_id = uuid4()
    grid_config_id = (
        await session.execute(
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
            await session.execute(
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
    await session.execute(
        text(
            """
            INSERT INTO block_index_aggregates
                (time, block_id, index_code, product_id, mean,
                 valid_pixel_count, total_pixel_count, stac_item_id)
            VALUES (:t, :b, 'ndvi', :p, :m, 100, 100, 'edr-scene')
            """
        ),
        {"t": observed, "b": block_id, "p": product_id, "m": _HIGH},
    )
    for cell_id, mean in zip(cells, (_HIGH, _LOW), strict=True):
        await session.execute(
            text(
                """
                INSERT INTO block_grid_aggregates
                    (time, cell_id, block_id, index_code, product_id, mean,
                     valid_pixel_count, total_pixel_count, stac_item_id)
                VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, 'edr-scene')
                """
            ),
            {"t": observed, "c": cell_id, "b": block_id, "p": product_id, "m": mean},
        )
    return block_id


async def _seed(admin_session: Any) -> dict[str, Any]:
    """One farm, two blocks, two cells each."""
    if not _SHARED:
        slug = f"estate-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

        farm_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO farms (
                        code, name, country_code, boundary, boundary_utm, centroid, area_m2
                    ) VALUES (
                        'EDR-FARM', 'Estate dry run farm', 'EG',
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

        blocks = [
            await _seed_block(admin_session, farm_id=farm_id, code=f"EDR-0{n}") for n in (1, 2)
        ]
        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            tenant_id=tenant.tenant_id,
            farm_id=farm_id,
            blocks=blocks,
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


async def _make_tree(admin_session: Any, seeded: dict[str, Any]) -> dict[str, Any]:
    service = FoldingTreeAuthorService(public_session=admin_session, tenant_id=seeded["tenant_id"])
    code = f"estate_{uuid4().hex[:8]}"
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{seeded["schema"]}", public'))
    return {"service": service, "tree": tree, "code": code}


@pytest.mark.asyncio
async def test_estate_dry_run_covers_every_block_and_writes_no_card(admin_session: Any) -> None:
    seeded = await _seed(admin_session)
    made = await _make_tree(admin_session, seeded)
    service = EstateDryRunService(
        author_service=made["service"],
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    repo = EstateDryRunRepository(tenant_session=admin_session)
    run_id = await repo.open_run(
        tree_id=made["tree"]["id"],
        tree_code=made["code"],
        tree_name="Estate dry run tree",
        version_id=None,
        scope="cell",
        requested_by=None,
    )

    before = await _counts(admin_session)
    report = await service.run(tree_id=made["tree"]["id"], run_id=run_id)
    after = await _counts(admin_session)

    assert before == after, f"the estate dry run wrote rows: {before} -> {after}"

    # Two blocks, two cells each. A run that folded one block would say 2.
    assert report["blocks_evaluated"] == 2
    assert report["cells_evaluated"] == 4
    assert report["cells_no_findings"] == 2
    assert report["cells_no_findings_pct"] == 50.0
    assert report["cells_carded"] == 2
    assert report["cells_errored"] == 0

    sets = report["finding_sets"]
    assert [s["label"] for s in sets] == ["{ndvi_low}"]
    assert sets[0]["count"] == 2
    assert sets[0]["blocks"] == 2
    assert sets[0]["composed"] is False

    # The rule is named by the `code` the definition gave it, which is what
    # the author reads in the designer and what design section 9 prints.
    # This asserted the set label `{ndvi_low}` until the compiler carried a
    # rule's `code`: `_check_combinations` kept codes, action_type, status and
    # both texts and dropped `code`, so no author-given rule id survived a
    # publish and `rule_label` had nothing to fall back on but the set.
    assert sets[0]["matched_rule"] == "r_low"

    # One rule of two fired. The other names a code no node registers, which
    # is exactly the "wrong or unreachable" case the report exists to show.
    # Named by its own code, for the same reason as `matched_rule` above: an
    # author told to go and fix a rule needs the name they gave it, not the
    # set it happens to cover.
    assert report["rules_defined"] == 2
    assert report["rules_fired"] == 1
    assert report["rules_never_fired"] == ["r_never"]
    assert report["composed_share_pct"] == 0.0
    assert report["timing"]["total_ms"] > 0


@pytest.mark.asyncio
async def test_the_report_row_holds_the_report(admin_session: Any) -> None:
    """The run is readable afterwards, which is the point of storing it."""
    seeded = await _seed(admin_session)
    made = await _make_tree(admin_session, seeded)
    repo = EstateDryRunRepository(tenant_session=admin_session)
    run_id = await repo.open_run(
        tree_id=made["tree"]["id"],
        tree_code=made["code"],
        tree_name="Estate dry run tree",
        version_id=None,
        scope="cell",
        requested_by=None,
    )
    opened = await repo.get_run(run_id=run_id)
    assert opened is not None
    assert opened["state"] == "running"
    assert opened["report"] == {}

    service = EstateDryRunService(
        author_service=made["service"],
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    await service.run(tree_id=made["tree"]["id"], run_id=run_id)

    stored = await repo.get_run(run_id=run_id)
    assert stored is not None
    assert stored["state"] == "done"
    assert stored["cells_evaluated"] == 4
    assert stored["cells_errored"] == 0
    assert stored["duration_ms"] is not None
    assert stored["report"]["finding_sets"][0]["label"] == "{ndvi_low}"

    listed = await repo.list_runs(tree_id=made["tree"]["id"])
    assert [row["id"] for row in listed] == [run_id]
    # The list view leaves the report document out; it is read one run at a
    # time and is tens of kilobytes.
    assert "report" not in listed[0]


@pytest.mark.asyncio
async def test_block_limit_folds_the_first_blocks_only(admin_session: Any) -> None:
    """For a first look at a large tenant, and for these tests."""
    seeded = await _seed(admin_session)
    made = await _make_tree(admin_session, seeded)
    service = EstateDryRunService(
        author_service=made["service"],
        tenant_session=admin_session,
        tenant_schema=seeded["schema"],
    )
    repo = EstateDryRunRepository(tenant_session=admin_session)
    run_id = await repo.open_run(
        tree_id=made["tree"]["id"],
        tree_code=made["code"],
        tree_name=None,
        version_id=None,
        scope="cell",
        requested_by=None,
    )

    report = await service.run(tree_id=made["tree"]["id"], run_id=run_id, block_limit=1)

    assert report["blocks_evaluated"] == 1
    assert report["cells_evaluated"] == 2


@pytest.mark.asyncio
async def test_real_run_results_are_empty_before_the_tree_is_on_the_sweep(
    admin_session: Any,
) -> None:
    """Stage A and B write no trace, so this list is empty and says nothing false.

    The query itself is exercised: it reads the three fold columns from
    tenant migration 0095 and joins `public.decision_trees` for the tree name,
    because a trace row carries no name of its own.
    """
    seeded = await _seed(admin_session)
    made = await _make_tree(admin_session, seeded)
    repo = EstateDryRunRepository(tenant_session=admin_session)

    rows = await repo.list_real_run_results(tree_id=made["tree"]["id"])

    assert rows == []
