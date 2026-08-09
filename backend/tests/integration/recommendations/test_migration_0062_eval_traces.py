"""Migration 0062 (evaluation lineage) — names, round-trip, and CHECKs.

Same reasoning as the 0059 round-trip test: the create side of a migration is
exercised by every test run, the drop side only by a rollback, which is
discovered to be broken at the worst possible moment. Convention-doubled
constraint names (``ck_x_ck_x_status``) have bitten this repo before, so the
names are read back from the catalog rather than assumed.

The CHECKs matter beyond tidiness. A trace whose ``status`` is a typo reads as
a legitimate verdict, and a ``skipped`` row with no ``skip_axis`` is exactly
the non-answer this whole table exists to replace — both are worse stored than
rejected.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

_TABLES = ("decision_tree_eval_runs", "decision_tree_eval_traces")
_CONSTRAINTS = {
    "decision_tree_eval_runs": (
        "ck_decision_tree_eval_runs_kind",
        "ck_decision_tree_eval_runs_outcome",
        "ck_decision_tree_eval_runs_finish_after_start",
    ),
    "decision_tree_eval_traces": (
        "ck_decision_tree_eval_traces_status",
        "ck_decision_tree_eval_traces_scope",
        "ck_decision_tree_eval_traces_skip_axis",
        "ck_decision_tree_eval_traces_skipped_names_axis",
        "ck_decision_tree_eval_traces_cell_implies_cell_scope",
    ),
}
_INDEXES = (
    "ix_decision_tree_eval_runs_started",
    "ix_decision_tree_eval_traces_block",
    "ix_decision_tree_eval_traces_tree",
    "ix_decision_tree_eval_traces_run",
)


def _alembic_cfg(schema: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


async def _new_tenant_schema(admin_session: Any, prefix: str) -> str:
    slug = f"{prefix}-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    return str(tenant.schema_name)


async def _table_exists(session: Any, schema: str, table: str) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t)"
                ),
                {"s": schema, "t": table},
            )
        ).scalar_one()
    )


async def _constraint_names(session: Any, schema: str, table: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
                "WHERE ns.nspname = :s AND rel.relname = :t"
            ),
            {"s": schema, "t": table},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _index_names(session: Any, schema: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT indexname FROM pg_indexes " "WHERE schemaname = :s AND tablename = ANY(:t)"
            ),
            {"s": schema, "t": list(_TABLES)},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _use_schema(session: Any, schema: str) -> None:
    """Point the session at the tenant schema.

    Re-applied after every rollback below: a plain ``SET`` is undone by
    ROLLBACK, so a test that deliberately aborts a statement loses its
    search_path along with the failed insert.
    """
    await session.execute(text(f'SET search_path TO "{schema}", public'))


async def _seed_run(session: Any, schema: str) -> str:
    """Insert a run and **commit** it, so it survives the rollbacks the
    constraint tests perform after each rejected insert."""
    await _use_schema(session, schema)
    run_id = (
        await session.execute(
            text("INSERT INTO decision_tree_eval_runs (kind) VALUES ('on_demand') RETURNING id")
        )
    ).scalar_one()
    await session.commit()
    await _use_schema(session, schema)
    return str(run_id)


def _insert_trace(**overrides: Any) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "cell_id": None,
        "scope": "block",
        "status": "clear",
        "skip_axis": None,
    }
    params.update(overrides)
    sql = """
        INSERT INTO decision_tree_eval_traces (
            run_id, farm_id, block_id, cell_id,
            tree_id, tree_code, tree_version, scope, status, skip_axis
        ) VALUES (
            :run_id, gen_random_uuid(), gen_random_uuid(), :cell_id,
            gen_random_uuid(), 'demo_v1', 1, :scope, :status, :skip_axis
        )
    """
    return sql, params


@pytest.mark.asyncio
async def test_0062_creates_the_names_its_downgrade_drops(admin_session: Any) -> None:
    schema = await _new_tenant_schema(admin_session, "mig62")

    for table in _TABLES:
        assert await _table_exists(admin_session, schema, table), f"{table} missing"
        cons = await _constraint_names(admin_session, schema, table)
        for name in _CONSTRAINTS[table]:
            assert name in cons, f"{name!r} missing — have {sorted(cons)}"

    idx = await _index_names(admin_session, schema)
    for name in _INDEXES:
        assert name in idx, f"{name!r} missing — have {sorted(idx)}"


@pytest.mark.asyncio
async def test_0062_round_trips(admin_session: Any) -> None:
    """Down to 0061, back up to head, and both tables are whole again."""
    schema = await _new_tenant_schema(admin_session, "mig62r")

    cfg = _alembic_cfg(schema)
    command.downgrade(cfg, "0061")
    for table in _TABLES:
        assert not await _table_exists(admin_session, schema, table)

    command.upgrade(cfg, "head")
    for table in _TABLES:
        assert await _table_exists(admin_session, schema, table)
    assert set(_INDEXES) <= await _index_names(admin_session, schema)


@pytest.mark.asyncio
async def test_a_skipped_trace_must_name_the_axis_that_rejected_it(
    admin_session: Any,
) -> None:
    """ "skipped" with no axis is the non-answer the table exists to replace."""
    schema = await _new_tenant_schema(admin_session, "mig62a")
    run_id = await _seed_run(admin_session, schema)

    sql, params = _insert_trace(run_id=run_id, status="skipped", skip_axis=None)
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()
    await _use_schema(admin_session, schema)

    # With the axis named, the same row is accepted.
    sql, params = _insert_trace(run_id=run_id, status="skipped", skip_axis="country")
    await admin_session.execute(text(sql), params)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_status_and_axis_vocabularies_are_enforced(admin_session: Any) -> None:
    schema = await _new_tenant_schema(admin_session, "mig62v")
    run_id = await _seed_run(admin_session, schema)

    sql, params = _insert_trace(run_id=run_id, status="definitely_not_a_status")
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()
    await _use_schema(admin_session, schema)

    sql, params = _insert_trace(run_id=run_id, status="skipped", skip_axis="vibes")
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_a_cell_id_cannot_ride_on_a_block_scoped_trace(admin_session: Any) -> None:
    """A block-scoped walk has no cell. Storing one would attribute a
    block-level verdict to a zone that never had its own evaluation."""
    schema = await _new_tenant_schema(admin_session, "mig62c")
    run_id = await _seed_run(admin_session, schema)

    sql, params = _insert_trace(run_id=run_id, scope="block", cell_id=str(uuid4()))
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_traces_cascade_when_their_run_is_deleted(admin_session: Any) -> None:
    """Retention is deferred, but it will be expressed as "delete old runs" —
    which only works if the traces follow."""
    schema = await _new_tenant_schema(admin_session, "mig62x")
    run_id = await _seed_run(admin_session, schema)

    sql, params = _insert_trace(run_id=run_id)
    await admin_session.execute(text(sql), params)
    remaining = (
        await admin_session.execute(
            text("SELECT count(*) FROM decision_tree_eval_traces WHERE run_id = :r"),
            {"r": run_id},
        )
    ).scalar_one()
    assert remaining == 1

    await admin_session.execute(
        text("DELETE FROM decision_tree_eval_runs WHERE id = :r"), {"r": run_id}
    )
    remaining = (
        await admin_session.execute(
            text("SELECT count(*) FROM decision_tree_eval_traces WHERE run_id = :r"),
            {"r": run_id},
        )
    ).scalar_one()
    assert remaining == 0
    await admin_session.rollback()
