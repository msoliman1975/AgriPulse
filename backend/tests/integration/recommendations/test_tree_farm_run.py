"""On-demand tree run over a farm — the authoring "run this now" path.

The dry-run answers "what would this tree decide here?" and writes
nothing. ``run_tree_on_farm`` decides it and puts the result in the
Action Center. These tests cover the four things that separate it from a
dry-run and from the nightly sweep:

  * it writes real ``recommendations`` rows, for every targeted block of
    the farm and no block outside it;
  * it walks **only** the named tree, leaving the tenant's other trees
    untouched — the whole point of a targeted run;
  * a re-run opens nothing and says so via ``deduped``, rather than
    reporting a silent zero that reads as failure;
  * it refuses a tree the sweep itself would skip (archived / inactive /
    unpublished), instead of writing nothing and calling it success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.errors import (
    DecisionTreeNotRunnableError,
    FarmNotFoundError,
)
from app.modules.recommendations.loader import sync_from_disk
from app.modules.recommendations.service import (
    get_decision_trees_author_service,
    get_recommendations_service,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]

# Crop-agnostic, block-scoped, and its stressed leaf is
# `kind: recommendation` — so it fires on a bare seeded block with no crop
# assignment, which is what keeps this fixture small.
#
# This used to borrow `scout_for_stress_v1` from the shipped catalogue. That
# tree was archived in public migration 0073 (hardcoded thresholds, and it
# asked the same question as `mango_canopy_health_v1` on a mango block), and
# no other shipped tree has this shape: the remaining crop-agnostic one
# raises an alert rather than a recommendation. So the fixture now carries
# its own tree, authored per tenant by `_make_tenant`. That also removes the
# old coupling where a change to a shipped seed could move these assertions.
# `public.decision_trees` still carries a legacy UNIQUE(code) that a migration
# test re-adds on downgrade, so two tenants may not both author the same code.
# Each tenant therefore gets its own, and `_make_tenant` hands it back on the
# returned object.
_TREE_CODE_PREFIX = "farm_run_fixture"

RUN_TREE_YAML = """
code: {code}
name_en: Farm-run fixture — NDVI below baseline
name_ar: قاعدة اختبار — NDVI دون خط الأساس
root: root
nodes:
  root:
    label_en: Is NDVI far below its seasonal baseline?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -1.5
    on_match: leaf_scout
    on_miss: leaf_no_action
  leaf_scout:
    label_en: Severe drop — scout
    outcome:
      action_type: scout
      severity: critical
      confidence: 0.85
      valid_for_hours: 72
      text_en: Scout this block.
      text_ar: استكشف هذه القطعة.
  leaf_no_action:
    label_en: No action
    outcome:
      action_type: no_action
      severity: info
      confidence: 0.9
      text_en: Within baseline.
      text_ar: ضمن خط الأساس.
"""


async def _seed_farm(
    admin: AsyncSession,
    schema: str,
    *,
    code: str,
    block_count: int,
    deviation: Decimal,
) -> tuple[UUID, list[UUID]]:
    """One farm with ``block_count`` active blocks, each carrying an NDVI
    aggregate at ``deviation`` sigma below baseline."""
    farm_id = uuid4()
    product_id = uuid4()
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await admin.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, :code, :name, "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id, "code": code, "name": f"Farm {code}"},
    )
    block_ids: list[UUID] = []
    for i in range(block_count):
        block_id = uuid4()
        block_ids.append(block_id)
        await admin.execute(
            text(
                "INSERT INTO blocks (id, farm_id, code, name, boundary, boundary_utm, "
                "                    centroid, area_m2, aoi_hash, unit_type) "
                "VALUES (:bid, :fid, :code, :name, "
                "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, "
                "31.2 30.11, 31.2 30.1))'::geometry, "
                "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
                "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
                "        50, :aoi, 'block')"
            ).bindparams(
                bindparam("bid", type_=PG_UUID(as_uuid=True)),
                bindparam("fid", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "bid": block_id,
                "fid": farm_id,
                "code": f"{code}-B{i}",
                "name": f"{code} block {i}",
                "aoi": f"{code}-aoi-{i}",
            },
        )
        await admin.execute(
            text(
                "INSERT INTO block_index_aggregates ("
                "  time, block_id, index_code, product_id, mean, "
                "  valid_pixel_count, total_pixel_count, stac_item_id, baseline_deviation"
                ") VALUES ("
                "  :time, :block_id, 'ndvi', :product_id, 0.45, "
                "  100, 100, :scene, :deviation"
                ")"
            ).bindparams(
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("product_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "time": datetime.now(UTC).replace(microsecond=0),
                "block_id": block_id,
                "product_id": product_id,
                "scene": f"{code}/{i}/scene",
                "deviation": deviation,
            },
        )
    await admin.commit()
    return farm_id, block_ids


async def _run(schema: str, tenant_id: UUID, *, farm_id: UUID, tree_code: str) -> dict:
    """Drive the run through its own session pair, as the route does."""
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            return await svc.run_tree_on_farm(
                tree_code=tree_code,
                farm_id=farm_id,
                actor_user_id=None,
                tenant_schema=schema,
                tenant_id=tenant_id,
            )


async def _open_recommendations(admin: AsyncSession, schema: str, farm_id: UUID) -> list[dict]:
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = (
        (
            await admin.execute(
                text(
                    "SELECT block_id, tree_code, action_type, severity, state "
                    "FROM recommendations WHERE farm_id = :fid"
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


@dataclass(frozen=True, slots=True)
class _Fixture:
    """The tenant plus the code of the tree authored inside it."""

    tenant_id: UUID
    schema_name: str
    tree_code: str


async def _make_tenant(admin: AsyncSession, slug: str) -> _Fixture:
    await sync_from_disk(admin)
    tenancy = get_tenant_service(admin)
    tenant = await tenancy.create_tenant(
        slug=f"{slug}-{uuid4().hex[:6]}",
        name="Tree run",
        contact_email="ops@tree-run.test",
    )
    code = f"{_TREE_CODE_PREFIX}_{uuid4().hex[:8]}"
    await _publish_run_tree(tenant.tenant_id, code)
    return _Fixture(tenant_id=tenant.tenant_id, schema_name=tenant.schema_name, tree_code=code)


async def _publish_run_tree(tenant_id: UUID, code: str) -> None:
    """Author + publish the fixture tree for this tenant.

    Tenant-scoped rather than platform-scoped so each test owns its own copy:
    `public.decision_trees` is shared across tenants in this database, and a
    test that deactivates the tree would otherwise break every later test.
    """
    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        await author.create_tree(
            code=code,
            crop_code=None,
            tree_yaml=RUN_TREE_YAML.format(code=code),
            actor_user_id=None,
        )
        await author.publish_version(code=code, version=1, actor_user_id=None)


@pytest.mark.asyncio
async def test_run_opens_recommendations_for_every_block_of_the_named_farm(
    admin_session: AsyncSession,
) -> None:
    tenant = await _make_tenant(admin_session, "tree-run")
    target_farm, target_blocks = await _seed_farm(
        admin_session, tenant.schema_name, code="TGT", block_count=3, deviation=Decimal("-2.0")
    )
    # Same tenant, same stressed signal — must stay untouched. A farm run
    # that reached it would be a tenant-wide sweep wearing a farm's name.
    other_farm, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="OTH", block_count=2, deviation=Decimal("-2.0")
    )

    result = await _run(
        tenant.schema_name, tenant.tenant_id, farm_id=target_farm, tree_code=tenant.tree_code
    )

    assert result["blocks_evaluated"] == 3
    assert result["blocks_targeted"] == 3
    assert result["recommendations_opened"] == 3
    assert result["deduped"] == 0
    assert result["errors"] == 0
    assert result["tree_code"] == tenant.tree_code
    assert {b["block_id"] for b in result["blocks"]} == set(target_blocks)

    opened = await _open_recommendations(admin_session, tenant.schema_name, target_farm)
    assert len(opened) == 3
    assert {r["state"] for r in opened} == {"open"}
    assert {r["action_type"] for r in opened} == {"scout"}
    assert {r["severity"] for r in opened} == {"critical"}

    assert await _open_recommendations(admin_session, tenant.schema_name, other_farm) == []


@pytest.mark.asyncio
async def test_run_walks_only_the_named_tree(admin_session: AsyncSession) -> None:
    """The tenant sees several seed trees; a targeted run must write rows
    for exactly one of them."""
    tenant = await _make_tenant(admin_session, "tree-run-only")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="ONE", block_count=2, deviation=Decimal("-2.0")
    )

    result = await _run(
        tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=tenant.tree_code
    )

    # One tree per block, not "every visible tree" per block.
    assert result["blocks_evaluated"] == 2
    assert result["blocks"][0]["trees_evaluated"] == 1
    opened = await _open_recommendations(admin_session, tenant.schema_name, farm_id)
    assert {r["tree_code"] for r in opened} == {tenant.tree_code}


@pytest.mark.asyncio
async def test_rerun_reports_dedup_rather_than_a_silent_zero(
    admin_session: AsyncSession,
) -> None:
    tenant = await _make_tenant(admin_session, "tree-run-again")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="RPT", block_count=2, deviation=Decimal("-2.0")
    )

    first = await _run(
        tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=tenant.tree_code
    )
    second = await _run(
        tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=tenant.tree_code
    )

    assert first["recommendations_opened"] == 2
    # The tree fired both times; the partial UNIQUE on the open state
    # absorbed the second round. `deduped` is the only thing that
    # distinguishes this from "conditions no longer match".
    assert second["recommendations_opened"] == 0
    assert second["deduped"] == 2
    assert all(b["deduped"] == 1 for b in second["blocks"])
    assert len(await _open_recommendations(admin_session, tenant.schema_name, farm_id)) == 2


@pytest.mark.asyncio
async def test_run_records_a_closed_eval_run(admin_session: AsyncSession) -> None:
    """A pass that writes recommendations must leave lineage — otherwise
    the on-demand path is the one run nobody can audit afterwards."""
    tenant = await _make_tenant(admin_session, "tree-run-lineage")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="LIN", block_count=2, deviation=Decimal("-2.0")
    )

    result = await _run(
        tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=tenant.tree_code
    )

    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    run = (
        (
            await admin_session.execute(
                text(
                    "SELECT kind, outcome, finished_at, blocks_evaluated, "
                    "       recommendations_opened, traces_written "
                    "FROM decision_tree_eval_runs WHERE id = :rid"
                ).bindparams(bindparam("rid", type_=PG_UUID(as_uuid=True))),
                {"rid": result["run_id"]},
            )
        )
        .mappings()
        .one()
    )
    assert run["kind"] == "on_demand"
    assert run["outcome"] == "ok"
    assert run["finished_at"] is not None
    assert run["blocks_evaluated"] == 2
    assert run["recommendations_opened"] == 2

    traces = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM decision_tree_eval_traces "
                "WHERE run_id = :rid AND tree_code = :code"
            ).bindparams(bindparam("rid", type_=PG_UUID(as_uuid=True))),
            {"rid": result["run_id"], "code": tenant.tree_code},
        )
    ).scalar_one()
    assert traces == 2


BROKEN_TREE_YAML = """
code: {code}
name_en: Broken on purpose
root: root
nodes:
  root:
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -0.5
    on_match: leaf
    on_miss: leaf
  leaf:
    outcome:
      action_type: scout
      severity: warning
      confidence: 0.5
      text_en: fired
"""


@pytest.mark.asyncio
async def test_a_tree_that_blows_up_closes_the_run_as_failed(
    admin_session: AsyncSession,
) -> None:
    """The error path has to survive contact with the run row.

    ``decision_tree_eval_runs.outcome`` admits only 'ok' | 'failed' (tenant
    0062). Passing anything else raises a constraint violation while closing
    the run — turning "one tree errored" into "the whole request 500s", on
    exactly the run that already had something go wrong. No happy-path test
    reaches this branch, so it needs a tree that genuinely breaks.
    """
    tenant = await _make_tenant(admin_session, "tree-run-broken")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="BRK", block_count=1, deviation=Decimal("-2.0")
    )
    code = f"broken_tree_{uuid4().hex[:8]}"

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        # The authoring service writes the catalog through the *public*
        # session, so that one needs its own transaction — without begin() the
        # tree is never committed and the run below cannot see it.
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant.tenant_id
            )
            await author.create_tree(
                code=code,
                crop_code=None,
                tree_yaml=BROKEN_TREE_YAML.format(code=code),
                actor_user_id=None,
            )
            await author.publish_version(code=code, version=1, actor_user_id=None)

    # Break it *after* publish: the loader would reject a dangling root at
    # compile time, which is the point — only a stored tree can reach the
    # engine's own error branch.
    await admin_session.execute(
        text(
            "UPDATE public.decision_tree_versions v "
            "   SET tree_compiled = jsonb_set(v.tree_compiled, '{root}', '\"missing_node\"') "
            "  FROM public.decision_trees t "
            " WHERE t.id = v.tree_id AND t.code = :code"
        ),
        {"code": code},
    )
    await admin_session.commit()

    result = await _run(tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=code)

    assert result["errors"] == 1
    assert result["recommendations_opened"] == 0

    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    outcome = (
        await admin_session.execute(
            text("SELECT outcome FROM decision_tree_eval_runs WHERE id = :rid").bindparams(
                bindparam("rid", type_=PG_UUID(as_uuid=True))
            ),
            {"rid": result["run_id"]},
        )
    ).scalar_one()
    assert outcome == "failed"


@pytest.mark.asyncio
async def test_run_on_unknown_farm_is_rejected(admin_session: AsyncSession) -> None:
    tenant = await _make_tenant(admin_session, "tree-run-nofarm")
    with pytest.raises(FarmNotFoundError):
        await _run(
            tenant.schema_name, tenant.tenant_id, farm_id=uuid4(), tree_code=tenant.tree_code
        )


@pytest.mark.asyncio
async def test_run_of_a_tree_the_sweep_would_skip_is_rejected(
    admin_session: AsyncSession,
) -> None:
    """Deactivating the tree must fail the run loudly. Silently writing
    nothing would read to the author as "my conditions did not match"."""
    tenant = await _make_tenant(admin_session, "tree-run-inactive")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="OFF", block_count=1, deviation=Decimal("-2.0")
    )
    await admin_session.execute(
        text(
            "UPDATE public.decision_trees SET is_active = FALSE "
            "WHERE code = :code AND tenant_id = :tid"
        ),
        {"code": tenant.tree_code, "tid": tenant.tenant_id},
    )
    await admin_session.commit()
    try:
        with pytest.raises(DecisionTreeNotRunnableError):
            await _run(
                tenant.schema_name, tenant.tenant_id, farm_id=farm_id, tree_code=tenant.tree_code
            )
    finally:
        # Restore even though the row is this tenant's own copy: the run
        # helper resolves by code, and a later assertion in this test file
        # reading a deactivated row would be hard to trace back to here.
        await admin_session.execute(
            text(
                "UPDATE public.decision_trees SET is_active = TRUE "
                "WHERE code = :code AND tenant_id = :tid"
            ),
            {"code": tenant.tree_code, "tid": tenant.tenant_id},
        )
        await admin_session.commit()


@pytest.mark.asyncio
async def test_candidate_farms_reports_targeted_block_counts(
    admin_session: AsyncSession,
) -> None:
    tenant = await _make_tenant(admin_session, "tree-run-picker")
    farm_id, _ = await _seed_farm(
        admin_session, tenant.schema_name, code="PCK", block_count=3, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant.tenant_id
            )
            farms = await author.candidate_farms(code=tenant.tree_code, tenant_session=session)

    entry = next(f for f in farms if f["farm_id"] == farm_id)
    # Crop-agnostic tree: every block of the farm is in scope.
    assert entry["blocks_total"] == 3
    assert entry["blocks_targeted"] == 3
