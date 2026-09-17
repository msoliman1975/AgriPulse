"""A folding tree, run against a real block, writing real rows.

``folding_engine.py`` was unit tested against dictionaries before this change
and no code path in the application called it. These tests are the other end:
a folding tree in the catalogue, a block with imagery, and the sweep's own
method walking it.

Four behaviours, each of which a single-pass test cannot see:

  * **Supersede.** The open-card dedup index refuses a second insert without
    an error (``service.py``'s ``_persist_recommendation``), so a card whose
    finding set changed has to be closed before the new one is written. The
    four-run sequence in section 5.6 of the design is asserted literally.
  * **Three-layer parameters.** Declared default, then the tenant row, then
    the farm row — with two farms holding different values at once, because a
    single farm cannot tell "the farm row won" from "the tenant row won".
  * **The fold columns on a trace.** ``finding_set``, ``matched_rule`` and
    ``registered_by`` are written on every row whatever the status, unlike
    ``node_path`` and ``resolved_values`` whose grain is uneven by design.
  * **Both engines in one block.** A folding tree and an old-style tree
    evaluate side by side and each writes its own kind of card.

The tree is inserted into ``public.decision_trees`` directly rather than
authored through ``DecisionTreesAuthorService``: the compiler that accepts the
folding shape lands in a separate change, and these tests are about what
happens after a folding tree is published, not about publishing one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.service import get_recommendations_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


# --- the tree ---------------------------------------------------------------


def _folding_compiled(code: str) -> dict[str, Any]:
    """A two-check folding tree: water, then vigour, then stop.

    Both checks register and continue, which is the whole point of the shape:
    the vigour question is asked once, not once per answer to the water
    question. ``findings`` travels with the tree so these tests do not depend
    on the catalogue tables, which arrive in a separate change.
    """
    return {
        "code": code,
        "name_en": "Folding demo",
        "name_ar": None,
        "root": "check_dry",
        "parameters": {"dry_threshold": {"type": "number", "default": 0.30}},
        "registers": ["dry", "ndvi_low"],
        "findings": {
            "dry": {
                "clause_en": "leaf water is low",
                "clause_ar": "محتوى الماء في الأوراق منخفض",
                "name_en": "Dry",
                "name_ar": "جفاف",
                "default_status": "stressed",
                "action_type": "irrigate",
            },
            "ndvi_low": {
                "clause_en": "canopy vigour dropped",
                "clause_ar": "انخفضت حيوية المجموع الخضري",
                "name_en": "Low vigour",
                "name_ar": "ضعف الحيوية",
                "default_status": "watch",
                "action_type": "scout",
            },
        },
        "combinations": [
            {
                "code": "dry_plus_vigour",
                "codes": ["dry", "ndvi_low"],
                "action_type": "irrigate",
                "status": "stressed",
                "text_en": "Water shortage is the cause. Irrigate before treating anything else.",
                "text_ar": "نقص الماء هو السبب. اروِ قبل أي معالجة أخرى.",
            }
        ],
        "nodes": {
            "check_dry": {
                "label_en": "Is leaf water low?",
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndmi", "key": "mean"},
                        "right": {"source": "params", "name": "dry_threshold"},
                    }
                },
                "on_match": "reg_dry",
                "on_miss": "check_ndvi",
            },
            "reg_dry": {"register": {"code": "dry", "severity": "warning"}, "next": "check_ndvi"},
            "check_ndvi": {
                "label_en": "Has canopy vigour dropped?",
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                        "right": 0.40,
                    }
                },
                "on_match": "reg_ndvi",
                "on_miss": "stop",
            },
            "reg_ndvi": {
                "register": {"code": "ndvi_low", "severity": "critical"},
                "next": "stop",
            },
            "stop": {"stop": True, "label_en": "Fold"},
        },
    }


def _old_style_compiled(code: str) -> dict[str, Any]:
    """The engine this repository has always had: one walk, one leaf."""
    return {
        "code": code,
        "name_en": "Leaf demo",
        "name_ar": None,
        "root": "root",
        "nodes": {
            "root": {
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndmi", "key": "mean"},
                        "right": 0.30,
                    }
                },
                "on_match": "leaf_scout",
                "on_miss": "leaf_noop",
            },
            "leaf_scout": {
                "outcome": {
                    "action_type": "scout",
                    "severity": "warning",
                    "confidence": 0.8,
                    "text_en": "Scout this block for water stress.",
                }
            },
            "leaf_noop": {"outcome": {"action_type": "no_action", "text_en": "Nothing to do."}},
        },
    }


async def _install_tree(session: AsyncSession, *, compiled: dict[str, Any]) -> UUID:
    """Publish one tree straight into the catalogue. Returns its id."""
    tree_id, version_id = uuid4(), uuid4()
    await session.execute(text("SET LOCAL search_path TO public"))
    await session.execute(
        text(
            """
            INSERT INTO public.decision_trees
                (id, code, tenant_id, name_en, scope, is_active)
            VALUES (:id, :code, NULL, :name_en, 'block', TRUE)
            """
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": tree_id, "code": compiled["code"], "name_en": compiled["name_en"]},
    )
    await session.execute(
        text(
            """
            INSERT INTO public.decision_tree_versions
                (id, tree_id, version, tree_yaml, tree_compiled, compiled_hash, published_at)
            VALUES (:vid, :tid, 1, :yaml, CAST(:compiled AS jsonb), :hash, public.app_now())
            """
        ).bindparams(
            bindparam("vid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "vid": version_id,
            "tid": tree_id,
            "yaml": f"code: {compiled['code']}\n",
            "compiled": json.dumps(compiled),
            "hash": uuid4().hex,
        },
    )
    await session.execute(
        text(
            "UPDATE public.decision_trees SET current_version_id = :vid WHERE id = :tid"
        ).bindparams(
            bindparam("vid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"vid": version_id, "tid": tree_id},
    )
    await session.commit()
    return tree_id


# --- the field --------------------------------------------------------------


async def _seed_farm_and_block(
    session: AsyncSession, schema: str, *, suffix: str
) -> tuple[UUID, UUID]:
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, :code, :name, "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, 100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id, "code": f"FOLD-{suffix}", "name": f"Folding farm {suffix}"},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type) "
            "VALUES (:bid, :fid, :code, "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, 50, :aoi, 'block')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id, "code": f"B-{suffix}", "aoi": f"aoi-{suffix}"},
    )
    await session.commit()
    return farm_id, block_id


# Strictly increasing, one step per reading written. The context takes the
# latest row per index with `ORDER BY index_code, time DESC`, and two rows on
# the same timestamp would leave which reading wins up to the planner — a test
# that passes until it does not.
_READING_CLOCK = {"step": 0}


async def _write_index(
    session: AsyncSession,
    schema: str,
    *,
    block_id: UUID,
    index_code: str,
    mean: Decimal,
) -> None:
    """One imagery reading, later than every reading written before it."""
    _READING_CLOCK["step"] += 1
    # Monotonically later. Subtracting a growing number of minutes walked the
    # clock backwards, so a later write landed before an earlier one and
    # "latest reading per index" picked the wrong row.
    at = (
        datetime.now(UTC).replace(microsecond=0)
        - timedelta(days=30)
        + timedelta(minutes=_READING_CLOCK["step"])
    )
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO block_index_aggregates ("
            "  time, block_id, index_code, product_id, mean, "
            "  valid_pixel_count, total_pixel_count, stac_item_id"
            ") VALUES (:time, :block_id, :index_code, :product_id, :mean, 100, 100, :stac)"
        ).bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("product_id", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "time": at,
            "block_id": block_id,
            "index_code": index_code,
            "product_id": uuid4(),
            "mean": mean,
            "stac": f"fold/{uuid4().hex[:8]}",
        },
    )
    await session.commit()


async def _evaluate(
    schema: str, tenant_id: UUID, block_id: UUID, *, only_tree_code: str | None = None
) -> UUID:
    """One evaluation pass over one block, inside a run so traces are written.

    Its own session, committed on exit, exactly as the sweep runs it.
    """
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            run_id = await svc.repo.open_eval_run(kind="on_demand", actor_user_id=None)
            await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=schema,
                tenant_id=tenant_id,
                run_id=run_id,
                only_tree_code=only_tree_code,
            )
    return run_id


async def _cards(session: AsyncSession, schema: str, *, block_id: UUID) -> list[dict[str, Any]]:
    # Re-applied on every read: a commit anywhere drops the search_path with
    # no error to say so, and the next read then finds an empty list.
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = await session.execute(
        text(
            """
            SELECT id, state, severity, action_type, finding_set, text_en, created_at
              FROM recommendations
             WHERE block_id = :b
             ORDER BY created_at, id
            """
        ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
        {"b": block_id},
    )
    return [dict(r) for r in rows.mappings().all()]


async def _traces(session: AsyncSession, schema: str, *, run_id: UUID) -> list[dict[str, Any]]:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = await session.execute(
        text(
            """
            SELECT status, tree_code, finding_set, matched_rule, registered_by,
                   node_path, resolved_values
              FROM decision_tree_eval_traces
             WHERE run_id = :r
             ORDER BY tree_code
            """
        ).bindparams(bindparam("r", type_=PG_UUID(as_uuid=True))),
        {"r": run_id},
    )
    return [dict(r) for r in rows.mappings().all()]


async def _tenant_for(admin_session: AsyncSession, slug: str) -> Any:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"{slug}-{uuid4().hex[:6]}", name=slug, contact_email=f"ops@{slug}.test"
    )
    await admin_session.commit()
    return tenant


# --- supersede --------------------------------------------------------------


@pytest.mark.asyncio
async def test_four_runs_supersede_the_open_card(admin_session: AsyncSession) -> None:
    """The sequence in design 5.6, run for run.

    run 1: {dry}             -> card A (warning) open
    run 2: {dry, ndvi_low}   -> card A closed, card B (critical) open
    run 3: {dry, ndvi_low}   -> card B untouched
    run 4: {dry}             -> card B closed, card C (warning) open
    """
    tenant = await _tenant_for(admin_session, "fold-supersede")
    code = f"folding_supersede_{uuid4().hex[:6]}"
    await _install_tree(admin_session, compiled=_folding_compiled(code))
    _farm_id, block_id = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="sup")

    # Run 1 — dry only. NDMI below the threshold, NDVI healthy.
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.10"),
    )
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.60"),
    )
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    cards = await _cards(admin_session, tenant.schema_name, block_id=block_id)
    assert len(cards) == 1, cards
    card_a = cards[0]
    assert card_a["state"] == "open"
    assert card_a["severity"] == "warning"
    assert card_a["finding_set"] == ["dry"]

    # Run 2 — vigour drops as well. The set gained a code, so the open card
    # no longer describes the block and is closed.
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.20"),
    )
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    cards = await _cards(admin_session, tenant.schema_name, block_id=block_id)
    assert len(cards) == 2, cards
    assert cards[0]["id"] == card_a["id"]
    assert cards[0]["state"] == "expired"
    card_b = cards[1]
    assert card_b["state"] == "open"
    assert card_b["severity"] == "critical"
    assert card_b["finding_set"] == ["dry", "ndvi_low"]
    # Both codes, so the combination rule supplies the text rather than the
    # composed sentence.
    assert card_b["text_en"].startswith("Water shortage is the cause.")

    # Run 3 — nothing moved. The same set opens nothing and closes nothing.
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    cards = await _cards(admin_session, tenant.schema_name, block_id=block_id)
    assert len(cards) == 2, cards
    assert [c["state"] for c in cards] == ["expired", "open"]
    assert cards[1]["id"] == card_b["id"]

    # Run 4 — vigour recovers. The set lost a code: the card is still replaced,
    # because it says two things and only one is true, but nobody is told.
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.70"),
    )
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    cards = await _cards(admin_session, tenant.schema_name, block_id=block_id)
    assert len(cards) == 3, cards
    assert [c["state"] for c in cards] == ["expired", "expired", "open"]
    assert cards[1]["id"] == card_b["id"]
    assert cards[2]["finding_set"] == ["dry"]
    assert cards[2]["severity"] == "warning"


@pytest.mark.asyncio
async def test_supersede_writes_a_history_row_naming_both_sets(
    admin_session: AsyncSession,
) -> None:
    """The close is recorded as a supersede, not as a bare expiry.

    ``expired`` is reused deliberately rather than adding a state to the check
    constraint, so the history row is the only place that says why the card
    ended. If it did not say, an expired card and a superseded one would be
    the same row to anybody reading the lineage later.
    """
    tenant = await _tenant_for(admin_session, "fold-history")
    code = f"folding_history_{uuid4().hex[:6]}"
    await _install_tree(admin_session, compiled=_folding_compiled(code))
    _farm_id, block_id = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="his")

    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.10"),
    )
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.60"),
    )
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.20"),
    )
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    rows = (
        (
            await admin_session.execute(
                text(
                    "SELECT from_state, to_state, details FROM recommendations_history "
                    " WHERE block_id = :b AND to_state = 'expired'"
                ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
                {"b": block_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1, rows
    details = rows[0]["details"]
    assert rows[0]["from_state"] == "open"
    assert details["reason"] == "superseded"
    assert details["finding_set_before"] == ["dry"]
    assert details["finding_set_after"] == ["dry", "ndvi_low"]
    # The set gained a code, so this replacement was announced.
    assert details["notified"] is True


# --- the fold columns on the trace ------------------------------------------


@pytest.mark.asyncio
async def test_every_trace_status_carries_the_fold_columns(
    admin_session: AsyncSession,
) -> None:
    """``fired``, ``clear`` and ``error`` rows all carry the three columns.

    The long payload stays conditional — a ``clear`` row keeps the node path
    and drops the resolved values, as migration 0062 describes. The fold
    columns do not follow that grain.
    """
    tenant = await _tenant_for(admin_session, "fold-trace")
    fired_code = f"folding_fired_{uuid4().hex[:6]}"
    broken_code = f"folding_broken_{uuid4().hex[:6]}"
    await _install_tree(admin_session, compiled=_folding_compiled(fired_code))

    # A tree whose register points at a node that does not exist: the walk
    # ends with an error rather than at a stop, and folds nothing.
    broken = _folding_compiled(broken_code)
    broken["nodes"]["reg_dry"]["next"] = "no_such_node"
    await _install_tree(admin_session, compiled=broken)

    _farm_id, block_id = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="trc")

    # Fired + error: NDMI is low, so both trees register `dry`.
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.10"),
    )
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.60"),
    )
    run_fired = await _evaluate(
        tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=fired_code
    )
    run_error = await _evaluate(
        tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=broken_code
    )

    fired = await _traces(admin_session, tenant.schema_name, run_id=run_fired)
    assert len(fired) == 1, fired
    assert fired[0]["status"] == "fired"
    assert fired[0]["finding_set"] == ["dry"]
    # One finding, so no combination rule matched and the text was composed.
    assert fired[0]["matched_rule"] is None
    assert fired[0]["registered_by"] == {"dry": ["reg_dry"]}

    errored = await _traces(admin_session, tenant.schema_name, run_id=run_error)
    assert len(errored) == 1, errored
    assert errored[0]["status"] == "error"
    # The findings collected before the walk broke are still recorded: a trace
    # is more useful with them than without.
    assert errored[0]["registered_by"] == {"dry": ["reg_dry"]}
    assert errored[0]["finding_set"] == []

    # Clear: the field recovers, the walk reaches stop with nothing registered.
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.80"),
    )
    run_clear = await _evaluate(
        tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=fired_code
    )
    cleared = await _traces(admin_session, tenant.schema_name, run_id=run_clear)
    assert len(cleared) == 1, cleared
    assert cleared[0]["status"] == "clear"
    assert cleared[0]["finding_set"] == []
    assert cleared[0]["matched_rule"] is None
    assert cleared[0]["registered_by"] == {}
    # The 0062 grain is unchanged: a clear row keeps the path, drops the values.
    assert cleared[0]["node_path"] != []
    assert cleared[0]["resolved_values"] == {}


@pytest.mark.asyncio
async def test_a_matched_combination_rule_is_named_on_the_trace(
    admin_session: AsyncSession,
) -> None:
    tenant = await _tenant_for(admin_session, "fold-rule")
    code = f"folding_rule_{uuid4().hex[:6]}"
    await _install_tree(admin_session, compiled=_folding_compiled(code))
    _farm_id, block_id = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="rul")
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.10"),
    )
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.20"),
    )
    run_id = await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=code)

    rows = await _traces(admin_session, tenant.schema_name, run_id=run_id)
    assert rows[0]["finding_set"] == ["dry", "ndvi_low"]
    assert rows[0]["matched_rule"] == "dry_plus_vigour"
    assert rows[0]["registered_by"] == {"dry": ["reg_dry"], "ndvi_low": ["reg_ndvi"]}


# --- three-layer parameters -------------------------------------------------


@pytest.mark.asyncio
async def test_parameters_resolve_default_then_tenant_then_farm(
    admin_session: AsyncSession,
) -> None:
    """Two farms, two answers, one tree, one reading.

    Both blocks have NDMI 0.25. The declared default is 0.30, so both are dry
    on defaults alone. The tenant row lowers the threshold to 0.20, which
    silences both. One farm raises its own to 0.40, and only that farm's block
    is dry again — which is the layering, seen from outside.
    """
    tenant = await _tenant_for(admin_session, "fold-params")
    code = f"folding_params_{uuid4().hex[:6]}"
    tree_id = await _install_tree(admin_session, compiled=_folding_compiled(code))

    farm_a, block_a = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="pa")
    farm_b, block_b = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="pb")
    for block in (block_a, block_b):
        await _write_index(
            admin_session,
            tenant.schema_name,
            block_id=block,
            index_code="ndmi",
            mean=Decimal("0.25"),
        )
        await _write_index(
            admin_session,
            tenant.schema_name,
            block_id=block,
            index_code="ndvi",
            mean=Decimal("0.60"),
        )

    # Layer 1 — the declared default of 0.30. 0.25 is below it, so both fire.
    for block in (block_a, block_b):
        await _evaluate(tenant.schema_name, tenant.tenant_id, block, only_tree_code=code)
    assert (await _cards(admin_session, tenant.schema_name, block_id=block_a))[0][
        "finding_set"
    ] == ["dry"]
    assert (await _cards(admin_session, tenant.schema_name, block_id=block_b))[0][
        "finding_set"
    ] == ["dry"]

    # Layer 2 — the tenant row at 0.20. Below the reading, so a new evaluation
    # finds nothing. (The cards already open stay open; closing a card whose
    # tree went quiet is a separate piece of work.)
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            await svc.repo.upsert_param_override(
                tree_id=tree_id, param_name="dry_threshold", value=0.20, actor_user_id=None
            )
            # Layer 3 — farm B keeps its own, higher threshold.
            await svc.repo.upsert_param_override(
                tree_id=tree_id,
                param_name="dry_threshold",
                value=0.40,
                actor_user_id=None,
                farm_id=farm_b,
            )

    run_a = await _evaluate(tenant.schema_name, tenant.tenant_id, block_a, only_tree_code=code)
    run_b = await _evaluate(tenant.schema_name, tenant.tenant_id, block_b, only_tree_code=code)

    trace_a = (await _traces(admin_session, tenant.schema_name, run_id=run_a))[0]
    trace_b = (await _traces(admin_session, tenant.schema_name, run_id=run_b))[0]
    # Farm A inherits the tenant row: 0.25 is above 0.20, nothing registers.
    assert trace_a["status"] == "clear"
    assert trace_a["finding_set"] == []
    # Farm B's own row wins over it: 0.25 is below 0.40, so the block is dry.
    assert trace_b["status"] == "fired"
    assert trace_b["finding_set"] == ["dry"]

    # The sweep reads the same two layers in one pass, so the same answers
    # must come out of the pre-read path as out of the per-block query.
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            by_farm = await svc.repo.list_param_overrides_by_farm()
    assert by_farm[None][tree_id] == {"dry_threshold": 0.20}
    assert by_farm[farm_b][tree_id] == {"dry_threshold": 0.40}
    assert farm_a not in by_farm


# --- both engines in one block ----------------------------------------------


@pytest.mark.asyncio
async def test_a_folding_tree_and_an_old_tree_both_run_on_one_block(
    admin_session: AsyncSession,
) -> None:
    """Dispatch is on the tree's shape, so the two live side by side.

    Each writes its own card against the same block and the same reading. The
    old tree's card has no findings — ``[]``, not null — and the folding
    tree's card carries the set it folded.
    """
    tenant = await _tenant_for(admin_session, "fold-mixed")
    folding_code = f"folding_mixed_{uuid4().hex[:6]}"
    leaf_code = f"leaf_mixed_{uuid4().hex[:6]}"
    await _install_tree(admin_session, compiled=_folding_compiled(folding_code))
    await _install_tree(admin_session, compiled=_old_style_compiled(leaf_code))
    _farm_id, block_id = await _seed_farm_and_block(admin_session, tenant.schema_name, suffix="mix")
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndmi",
        mean=Decimal("0.10"),
    )
    await _write_index(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        index_code="ndvi",
        mean=Decimal("0.60"),
    )

    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=folding_code)
    await _evaluate(tenant.schema_name, tenant.tenant_id, block_id, only_tree_code=leaf_code)

    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    rows = (
        (
            await admin_session.execute(
                text(
                    "SELECT tree_code, state, action_type, severity, finding_set, text_en "
                    "  FROM recommendations WHERE block_id = :b ORDER BY tree_code"
                ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
                {"b": block_id},
            )
        )
        .mappings()
        .all()
    )
    by_code = {r["tree_code"]: dict(r) for r in rows}
    assert set(by_code) == {folding_code, leaf_code}

    folded = by_code[folding_code]
    assert folded["state"] == "open"
    assert folded["finding_set"] == ["dry"]
    assert folded["action_type"] == "irrigate"
    assert folded["severity"] == "warning"
    # One finding, so the text is composed from its clause.
    assert "leaf water is low" in folded["text_en"].lower()

    leafed = by_code[leaf_code]
    assert leafed["state"] == "open"
    assert leafed["finding_set"] == []
    assert leafed["action_type"] == "scout"
    assert leafed["text_en"] == "Scout this block for water stress."
