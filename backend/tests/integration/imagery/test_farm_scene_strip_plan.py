"""The scene strip's cost is in its PLAN SHAPE, and nothing else can see it.

`GET /farms/{farm_id}/scenes` took **32 seconds** on prod for Green Farm
[Demo-01] — 4 blocks, 52 rows returned — while returning entirely correct
results. Every behavioural test in `test_farm_scene_strip_paths.py` passed
throughout. That is the whole problem: the defect was a correlated subquery
over `block_index_aggregates`, one execution per farm-pass day, and a
correlated subquery returns exactly the same rows as the grouped form. No
assertion on the response body can distinguish them.

What separated them was TimescaleDB chunk exclusion. A correlated `a.time =
p.at` is only known at run time, so chunks cannot be excluded at PLAN time and
the exclusion is re-done on every loop: 52 pass days x 495 chunks was ~26k
evaluations to produce 52 rows, and the `EXPLAIN` output ran to 3,629 lines
with 964 chunk scan nodes. Only 462 ms of the 32 s was actual row work.

So these assert on the plan. They are deliberately structural rather than a
latency budget — a wall-clock assertion would be flaky on CI and, worse, would
pass on a test container whose hypertable has three chunks instead of 495.
The chunk count is a property of prod's history; the plan shape is a property
of the SQL, and the plan shape is what we control.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.repository import _FARM_SCENE_DAYS_SQL

from .conftest import AsyncClient
from .test_farm_scene_strip_paths import (
    _farm_subscription,
    _insert_aggregate,
    _insert_farm_job,
    _setup,
)
from .test_subscription_crud import _get_s2l2a_product_id, _square_polygon

pytestmark = [pytest.mark.integration]

# Enough pass days that a per-day plan is unmistakable: a correlated subquery
# would report `loops=PASS_DAYS` on its scan of the hypertable, a grouped one
# reads it once regardless.
_PASS_DAYS = 8


# Everything the strip SQL binds except the farm. The query is scoped to the
# index the caller is about to draw, and through it to the products that can
# produce it — `ndvi` on `s2_l2a` is what the correlated version hardcoded, so
# these values keep this test measuring the same plan it was written against.
_STRIP_PARAMS: dict = {
    "limit": 120,
    "index_code": "ndvi",
    "product_codes": ["s2_l2a"],
}


async def _explain(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    farm_id: UUID,
) -> dict:
    """The shipped SQL's plan, as JSON, in the tenant's schema.

    ANALYZE on purpose: `loops` is the number this test is really about, and
    it only exists in an analysed plan.
    """
    await admin_session.execute(text(f'SET search_path TO "{tenant_schema}", public'))
    result = await admin_session.execute(
        text(f"EXPLAIN (ANALYZE, FORMAT JSON) {_FARM_SCENE_DAYS_SQL}").bindparams(
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("product_codes", expanding=True),
        ),
        _STRIP_PARAMS | {"farm": farm_id},
    )
    plan = result.scalar_one()
    # asyncpg hands back a JSON string; psycopg already decodes it.
    if isinstance(plan, str):
        plan = json.loads(plan)
    return plan[0]["Plan"]


def _walk(node: dict):
    """Every node in the plan tree, subplans included."""
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


async def _cut_over_farm_with_passes(
    admin_session: AsyncSession,
    client: AsyncClient,
    *,
    tenant_schema: str,
) -> tuple[UUID, UUID, UUID]:
    """A farm-AOI farm with `_PASS_DAYS` passes, indices computed for each.

    Farm-path specifically: that is the branch that carried the correlated
    subquery, and — per #462 — the branch a block-only test cannot reach.

    Hands back its subscription and product too: `uq_imagery_farm_subscriptions
    _active` is one row per (farm, product), so a caller that wants another
    pass has to reuse this one rather than make a second.
    """
    from .test_subscription_crud import _create_farm_and_block

    farm_id, block_a = await _create_farm_and_block(client)
    product_id = await _get_s2l2a_product_id(admin_session)
    block_b = (
        await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-PLAN-2", "boundary": _square_polygon(31.205, 30.005)},
        )
    ).json()["id"]
    sub = await _farm_subscription(
        admin_session,
        tenant_schema=tenant_schema,
        farm_id=UUID(farm_id),
        product_id=UUID(product_id),
    )
    base = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    for n in range(_PASS_DAYS):
        at = base - timedelta(days=n * 5)
        await _insert_farm_job(
            admin_session,
            tenant_schema=tenant_schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=sub,
            scene_id=f"PLAN_{n}",
            scene_datetime=at,
            stac_item_id=f"sentinel_hub/s2_l2a/PLAN_{n}/farmaoihash",
        )
        for block in (block_a, block_b):
            await _insert_aggregate(
                admin_session,
                tenant_schema=tenant_schema,
                block_id=UUID(block),
                product_id=UUID(product_id),
                at=at,
            )
    await admin_session.commit()
    return UUID(farm_id), sub, UUID(product_id)


@pytest.mark.asyncio
async def test_the_strip_reads_the_aggregates_hypertable_once_per_query(
    admin_session: AsyncSession,
) -> None:
    """The regression, stated as the plan property that made it 32 s.

    Every scan of `block_index_aggregates` must run a bounded number of times
    — not once per farm-pass day. `loops` scaling with pass days IS the bug:
    on prod that multiplied 495 chunk exclusions by 52 days.
    """
    schema, client = await _setup(admin_session, "strip-plan-loops")
    async with client:
        farm_id, _sub, _product = await _cut_over_farm_with_passes(
            admin_session, client, tenant_schema=schema
        )
        plan = await _explain(admin_session, tenant_schema=schema, farm_id=farm_id)

    offenders = [
        (n.get("Relation Name") or n.get("Alias"), n.get("Actual Loops"))
        for n in _walk(plan)
        if "block_index_aggregates" in (n.get("Relation Name") or "")
        and (n.get("Actual Loops") or 1) >= _PASS_DAYS
    ]
    assert not offenders, (
        "a scan of block_index_aggregates runs once per farm-pass day — "
        f"the correlated-subquery shape is back: {offenders}"
    )


@pytest.mark.asyncio
async def test_the_strip_plan_has_no_correlated_subplan(
    admin_session: AsyncSession,
) -> None:
    """The structural statement of the same thing.

    A `SubPlan` here is a per-row execution, which for this query means per
    farm-pass day. The grouped form joins instead, so the plan carries no
    SubPlan at all — a blunt invariant, but the blunt one is what survives a
    planner upgrade choosing a different join strategy.
    """
    schema, client = await _setup(admin_session, "strip-plan-subplan")
    async with client:
        farm_id, _sub, _product = await _cut_over_farm_with_passes(
            admin_session, client, tenant_schema=schema
        )
        plan = await _explain(admin_session, tenant_schema=schema, farm_id=farm_id)

    subplans = [
        n.get("Subplan Name") for n in _walk(plan) if n.get("Parent Relationship") == "SubPlan"
    ]
    assert not subplans, f"correlated SubPlan in the scene-strip plan: {subplans}"


@pytest.mark.asyncio
async def test_the_grouped_form_still_returns_the_correlated_form_s_rows(
    admin_session: AsyncSession,
) -> None:
    """The equivalence the rewrite rests on, pinned in CI.

    Verified on prod with EXCEPT ALL both ways on a farm-path and a block-path
    farm (0 rows differing). This is that check, against the shape the SQL
    replaced, so the two can never silently diverge — in particular the
    LEFT JOIN + COALESCE must keep answering 0, where `count()` over no rows
    did, for a pass whose indices never ran.
    """
    schema, client = await _setup(admin_session, "strip-plan-equiv")
    async with client:
        farm_id, sub, product_id = await _cut_over_farm_with_passes(
            admin_session, client, tenant_schema=schema
        )
        # A pass with NO aggregates at all — the COALESCE branch.
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=farm_id,
            product_id=product_id,
            subscription_id=sub,
            scene_id="PLAN_RAW",
            scene_datetime=datetime(2026, 6, 25, 8, 30, tzinfo=UTC),
            stac_item_id="sentinel_hub/s2_l2a/PLAN_RAW/farmaoihash",
        )
        await admin_session.commit()

        correlated = _FARM_SCENE_DAYS_SQL.replace(
            "COALESCE(g.computed_count, 0::bigint) AS computed_count",
            "(SELECT count(DISTINCT a.block_id)\n"
            "   FROM block_index_aggregates a\n"
            "   JOIN blocks ab ON ab.id = a.block_id\n"
            "  WHERE ab.farm_id = :farm\n"
            "    AND a.index_code = :index_code\n"
            "    AND a.time = p.at) AS computed_count",
        )
        assert correlated != _FARM_SCENE_DAYS_SQL, "the COALESCE branch moved — retarget this test"

        await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
        params = _STRIP_PARAMS | {"farm": farm_id}
        binds = (
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("product_codes", expanding=True),
        )
        shipped = (
            (await admin_session.execute(text(_FARM_SCENE_DAYS_SQL).bindparams(*binds), params))
            .mappings()
            .all()
        )
        reference = (
            (await admin_session.execute(text(correlated).bindparams(*binds), params))
            .mappings()
            .all()
        )

    assert [dict(r) for r in shipped] == [dict(r) for r in reference]
    # And the raw pass is present, undrawable — not dropped by the join.
    raw = [r for r in shipped if r["scene_date"].isoformat() == "2026-06-25"]
    assert len(raw) == 1, "a pass with no aggregates must survive the LEFT JOIN"
    assert raw[0]["computed_count"] == 0
