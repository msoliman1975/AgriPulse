"""A farm chooses which decision trees run on it, and a tenant chooses how
often the sweep runs.

Two features share this file because they are two halves of one question —
who controls the decision-tree engine — and they share a fixture.

Farm-level selection (tenant migration 0089):

  * a tree turned off for one farm stops opening recommendations for that
    farm's blocks, and keeps opening them for every other farm;
  * the skip is recorded as a trace row naming ``skip_axis='farm'``, so
    "why did this tree stop?" has an answer that is not "nobody knows";
  * turning a tree off leaves the recommendations it already opened alone;
  * turning it back on resumes it.

Per-tenant cadence (public migration 0080):

  * a tenant is dispatched when its cadence has elapsed and not before;
  * the tenant override beats the platform default;
  * a second tick in the same hour dispatches nobody twice.

Every assertion here is made against the rows the engine actually wrote,
not against the helper that computed them. A test that asserted the
exclusion set rather than the recommendations would pass even if the
filter were never wired into the sweep.
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

from app.modules.recommendations import tasks as rec_tasks
from app.modules.recommendations.errors import (
    DecisionTreeNotFoundError,
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

_CADENCE_KEY = "recommendations.sweep_cadence_hours"

# Crop-agnostic and block-scoped, so it fires on a bare seeded block with no
# crop assignment. Authored per tenant rather than borrowed from the shipped
# catalogue: `public.decision_trees` is shared across tenants in this
# database, and a test that turned a shipped tree off would reach into every
# other test.
SELECTION_TREE_YAML = """
code: {code}
name_en: Farm-selection fixture — NDVI below baseline
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


@dataclass(frozen=True, slots=True)
class _Fixture:
    tenant_id: UUID
    schema_name: str
    tree_code: str
    tree_id: UUID


async def _make_tenant(admin: AsyncSession, slug: str) -> _Fixture:
    await sync_from_disk(admin)
    tenancy = get_tenant_service(admin)
    tenant = await tenancy.create_tenant(
        slug=f"{slug}-{uuid4().hex[:6]}",
        name="Farm tree selection",
        contact_email="ops@farm-tree-selection.test",
    )
    code = f"farm_selection_{uuid4().hex[:8]}"
    tree_id = await _publish_tree(tenant.tenant_id, code)
    return _Fixture(
        tenant_id=tenant.tenant_id,
        schema_name=tenant.schema_name,
        tree_code=code,
        tree_id=tree_id,
    )


async def _publish_tree(tenant_id: UUID, code: str) -> UUID:
    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        await author.create_tree(
            code=code,
            crop_code=None,
            tree_yaml=SELECTION_TREE_YAML.format(code=code),
            actor_user_id=None,
        )
        await author.publish_version(code=code, version=1, actor_user_id=None)
        row = (
            await public_session.execute(
                text("SELECT id FROM public.decision_trees WHERE code = :c"),
                {"c": code},
            )
        ).one()
    return UUID(str(row.id))


async def _seed_farm(
    admin: AsyncSession, schema: str, *, code: str, block_count: int
) -> tuple[UUID, list[UUID]]:
    """One farm whose blocks all sit far below their NDVI baseline, so the
    fixture tree fires on every one of them."""
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
                "deviation": Decimal("-2.0"),
            },
        )
    await admin.commit()
    return farm_id, block_ids


async def _set_enabled(fixture: _Fixture, *, farm_id: UUID, tree_id: UUID, enabled: bool) -> dict:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{fixture.schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            return await svc.set_farm_tree_enabled(
                farm_id=farm_id,
                tree_id=tree_id,
                tenant_id=fixture.tenant_id,
                enabled=enabled,
                actor_user_id=None,
                tenant_schema=fixture.schema_name,
            )


async def _list_selection(fixture: _Fixture, farm_id: UUID) -> tuple[dict, ...]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{fixture.schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            return await svc.list_farm_tree_selection(farm_id=farm_id, tenant_id=fixture.tenant_id)


async def _open_recommendations(
    admin: AsyncSession, schema: str, farm_id: UUID, tree_code: str
) -> list[dict]:
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = (
        (
            await admin.execute(
                text(
                    "SELECT block_id, tree_code, state FROM recommendations "
                    "WHERE farm_id = :fid AND tree_code = :code"
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id, "code": tree_code},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _traces(admin: AsyncSession, schema: str, farm_id: UUID, tree_code: str) -> list[dict]:
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = (
        (
            await admin.execute(
                text(
                    "SELECT status, skip_axis, skip_detail FROM decision_tree_eval_traces "
                    "WHERE farm_id = :fid AND tree_code = :code"
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id, "code": tree_code},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# ---------- A: farm-level tree selection ------------------------------------


@pytest.mark.asyncio
async def test_disabled_tree_skips_only_the_farm_that_turned_it_off(
    admin_session: AsyncSession,
) -> None:
    tenant = await _make_tenant(admin_session, "sel-off")
    off_farm, off_blocks = await _seed_farm(
        admin_session, tenant.schema_name, code="OFF", block_count=2
    )
    on_farm, on_blocks = await _seed_farm(
        admin_session, tenant.schema_name, code="ON", block_count=2
    )

    result = await _set_enabled(tenant, farm_id=off_farm, tree_id=tenant.tree_id, enabled=False)
    assert result["changed"] is True

    await rec_tasks._evaluate_for_tenant_async(tenant.schema_name)

    # The farm that turned it off got nothing from this tree.
    assert (
        await _open_recommendations(admin_session, tenant.schema_name, off_farm, tenant.tree_code)
        == []
    )
    # Every other farm is untouched — the setting is per farm, not per tenant.
    opened = await _open_recommendations(
        admin_session, tenant.schema_name, on_farm, tenant.tree_code
    )
    assert {r["block_id"] for r in opened} == set(on_blocks)
    assert len(off_blocks) == 2  # the blocks existed; they were simply not evaluated


@pytest.mark.asyncio
async def test_disabled_tree_is_recorded_as_a_skipped_trace(
    admin_session: AsyncSession,
) -> None:
    """A tree that stops firing with no trace is a tree nobody can explain."""
    tenant = await _make_tenant(admin_session, "sel-trace")
    farm_id, blocks = await _seed_farm(admin_session, tenant.schema_name, code="TRC", block_count=2)

    await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False)
    await rec_tasks._evaluate_for_tenant_async(tenant.schema_name)

    traces = await _traces(admin_session, tenant.schema_name, farm_id, tenant.tree_code)
    assert len(traces) == len(blocks)
    assert {t["status"] for t in traces} == {"skipped"}
    assert {t["skip_axis"] for t in traces} == {"farm"}
    assert traces[0]["skip_detail"] == {"required": ["enabled"], "actual": "disabled"}


@pytest.mark.asyncio
async def test_turning_a_tree_off_leaves_its_open_recommendations_alone(
    admin_session: AsyncSession,
) -> None:
    """Agreed behaviour: disabling stops future evaluation and closes
    nothing. The open cards describe something that was true in the field."""
    tenant = await _make_tenant(admin_session, "sel-keep")
    farm_id, blocks = await _seed_farm(
        admin_session, tenant.schema_name, code="KEEP", block_count=2
    )

    await rec_tasks._evaluate_for_tenant_async(tenant.schema_name)
    before = await _open_recommendations(
        admin_session, tenant.schema_name, farm_id, tenant.tree_code
    )
    assert len(before) == len(blocks)

    await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False)

    after = await _open_recommendations(
        admin_session, tenant.schema_name, farm_id, tenant.tree_code
    )
    assert len(after) == len(before)
    assert {r["state"] for r in after} == {"open"}


@pytest.mark.asyncio
async def test_turning_a_tree_back_on_resumes_it(admin_session: AsyncSession) -> None:
    tenant = await _make_tenant(admin_session, "sel-back")
    farm_id, blocks = await _seed_farm(
        admin_session, tenant.schema_name, code="BACK", block_count=2
    )

    await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False)
    await rec_tasks._evaluate_for_tenant_async(tenant.schema_name)
    assert (
        await _open_recommendations(admin_session, tenant.schema_name, farm_id, tenant.tree_code)
        == []
    )

    result = await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=True)
    assert result["changed"] is True
    await rec_tasks._evaluate_for_tenant_async(tenant.schema_name)

    opened = await _open_recommendations(
        admin_session, tenant.schema_name, farm_id, tenant.tree_code
    )
    assert {r["block_id"] for r in opened} == set(blocks)


@pytest.mark.asyncio
async def test_selection_list_marks_the_disabled_tree_and_leaves_the_rest_on(
    admin_session: AsyncSession,
) -> None:
    tenant = await _make_tenant(admin_session, "sel-list")
    farm_id, _ = await _seed_farm(admin_session, tenant.schema_name, code="LIST", block_count=1)

    rows = await _list_selection(tenant, farm_id)
    assert all(r["enabled"] for r in rows)
    # The tenant's own tree is in the list beside the shipped catalogue.
    mine = next(r for r in rows if r["tree_id"] == tenant.tree_id)
    assert mine["source"] == "tenant"

    await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False)

    rows = await _list_selection(tenant, farm_id)
    assert next(r for r in rows if r["tree_id"] == tenant.tree_id)["enabled"] is False
    assert all(r["enabled"] for r in rows if r["tree_id"] != tenant.tree_id)


@pytest.mark.asyncio
async def test_repeating_a_toggle_reports_no_change(admin_session: AsyncSession) -> None:
    tenant = await _make_tenant(admin_session, "sel-idem")
    farm_id, _ = await _seed_farm(admin_session, tenant.schema_name, code="IDEM", block_count=1)

    assert (await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False))[
        "changed"
    ] is True
    assert (await _set_enabled(tenant, farm_id=farm_id, tree_id=tenant.tree_id, enabled=False))[
        "changed"
    ] is False


@pytest.mark.asyncio
async def test_unknown_farm_and_unknown_tree_are_404s(admin_session: AsyncSession) -> None:
    tenant = await _make_tenant(admin_session, "sel-404")
    farm_id, _ = await _seed_farm(admin_session, tenant.schema_name, code="404", block_count=1)

    with pytest.raises(FarmNotFoundError):
        await _set_enabled(tenant, farm_id=uuid4(), tree_id=tenant.tree_id, enabled=False)
    with pytest.raises(DecisionTreeNotFoundError):
        await _set_enabled(tenant, farm_id=farm_id, tree_id=uuid4(), enabled=False)


# ---------- B: per-tenant sweep cadence -------------------------------------


async def _dispatch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run one Beat tick, collecting the schemas it would enqueue."""
    enqueued: list[str] = []

    class _Delay:
        @staticmethod
        def delay(schema: str) -> None:
            enqueued.append(schema)

    monkeypatch.setattr(rec_tasks, "evaluate_for_tenant", _Delay)
    await rec_tasks._evaluate_sweep_async()
    return enqueued


async def _set_cadence(admin: AsyncSession, tenant_id: UUID, hours: int | None) -> None:
    await admin.execute(text("SET LOCAL search_path TO public"))
    if hours is None:
        await admin.execute(
            text(
                "DELETE FROM public.tenant_settings_overrides "
                "WHERE tenant_id = :tid AND key = :k"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tenant_id, "k": _CADENCE_KEY},
        )
    else:
        await admin.execute(
            text(
                "INSERT INTO public.tenant_settings_overrides "
                "  (tenant_id, key, value, updated_at) "
                "VALUES (:tid, :k, CAST(:v AS jsonb), now()) "
                "ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tenant_id, "k": _CADENCE_KEY, "v": str(hours)},
        )
    await admin.commit()


async def _age_last_dispatch(admin: AsyncSession, tenant_id: UUID, hours: int) -> None:
    await admin.execute(
        text(
            "UPDATE public.tenant_dt_dispatch "
            "SET last_dispatched_at = now() - make_interval(hours => :h) "
            "WHERE tenant_id = :tid"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tenant_id, "h": hours},
    )
    await admin.commit()


@pytest.mark.asyncio
async def test_a_new_tenant_is_dispatched_on_the_first_tick(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant with no dispatch row has never been swept, so it is due now.
    Waiting a full cadence for a brand-new tenant would look like the engine
    is broken on the day somebody first opens the app."""
    tenant = await _make_tenant(admin_session, "cad-new")

    assert tenant.schema_name in await _dispatch(monkeypatch)


@pytest.mark.asyncio
async def test_a_tenant_is_not_dispatched_twice_inside_its_cadence(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _make_tenant(admin_session, "cad-twice")

    assert tenant.schema_name in await _dispatch(monkeypatch)
    # Second tick, same hour. The default cadence is 24 hours.
    assert tenant.schema_name not in await _dispatch(monkeypatch)


@pytest.mark.asyncio
async def test_the_tenant_override_decides_when_the_next_sweep_runs(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six hours after the last sweep, a 4-hour tenant is due and a 24-hour
    tenant is not. This is the whole feature in one assertion."""
    fast = await _make_tenant(admin_session, "cad-fast")
    slow = await _make_tenant(admin_session, "cad-slow")
    await _set_cadence(admin_session, fast.tenant_id, 4)
    await _set_cadence(admin_session, slow.tenant_id, 24)

    await _dispatch(monkeypatch)
    await _age_last_dispatch(admin_session, fast.tenant_id, 6)
    await _age_last_dispatch(admin_session, slow.tenant_id, 6)

    due = await _dispatch(monkeypatch)
    assert fast.schema_name in due
    assert slow.schema_name not in due


@pytest.mark.asyncio
async def test_a_weekly_tenant_waits_a_week(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _make_tenant(admin_session, "cad-week")
    await _set_cadence(admin_session, tenant.tenant_id, 168)

    await _dispatch(monkeypatch)
    await _age_last_dispatch(admin_session, tenant.tenant_id, 100)
    assert tenant.schema_name not in await _dispatch(monkeypatch)

    await _age_last_dispatch(admin_session, tenant.tenant_id, 169)
    assert tenant.schema_name in await _dispatch(monkeypatch)
