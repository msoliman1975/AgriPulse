"""Migration 0091 (decision-tree verdicts) — names, CHECKs, and the open-row index.

Written in the same shape as the 0062 test, and for the same reasons: the
create side runs on every test run, the drop side only on a rollback, and
convention-doubled constraint names (``ck_x_ck_x_status``) have bitten this
repo before, so the names are read back from the catalog rather than assumed.

The index is the part only a real database can prove. ``cell_id`` is NULL on
a block-scoped verdict, and Postgres treats two NULLs as distinct, so a
unique index without ``COALESCE`` would silently fail to constrain exactly
the rows the map reads most. A second open verdict for one block and tree
would not be an error — it would be a coin toss over which one is current.
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

_TABLE = "decision_tree_block_verdicts"
_CONSTRAINTS = (
    "ck_decision_tree_block_verdicts_kind",
    "ck_decision_tree_block_verdicts_status_code",
    "ck_decision_tree_block_verdicts_severity",
    "ck_decision_tree_block_verdicts_scope",
    "ck_decision_tree_block_verdicts_cell_implies_cell_scope",
    "ck_decision_tree_block_verdicts_interval_ordered",
    "ck_decision_tree_block_verdicts_severity_iff_work_item",
)
_INDEXES = (
    "uq_dt_verdicts_open",
    "ix_dt_verdicts_farm_open",
    "ix_dt_verdicts_block_time",
    "ix_dt_verdicts_tree_time",
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


# One schema for every test that only reads the catalog or inserts rows. A
# schema per test replays 91 migrations and is what pushed the integration
# job past its budget last time.
_SHARED: dict[str, str] = {}


async def _shared_schema(admin_session: Any) -> str:
    if "name" not in _SHARED:
        _SHARED["name"] = await _new_tenant_schema(admin_session, "mig91")
    return _SHARED["name"]


async def _use_schema(session: Any, schema: str) -> None:
    """Point the session at the tenant schema.

    Re-applied after every rollback: a plain ``SET`` is undone by ROLLBACK,
    so a test that deliberately aborts a statement loses its search_path
    along with the failed insert, and the next read finds an empty list
    with no error to explain it.
    """
    await session.execute(text(f'SET search_path TO "{schema}", public'))


def _insert(**overrides: Any) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "block_id": str(uuid4()),
        "tree_id": str(uuid4()),
        "cell_id": None,
        "scope": "block",
        "kind": "status",
        "status_code": "good",
        "severity": None,
        "valid_to": None,
    }
    params.update(overrides)
    sql = """
        INSERT INTO decision_tree_block_verdicts (
            farm_id, block_id, cell_id, scope,
            tree_id, tree_code, tree_version, leaf_node_id,
            kind, status_code, severity, text_en,
            valid_from, valid_to, last_evaluated_at
        ) VALUES (
            gen_random_uuid(), :block_id, :cell_id, :scope,
            :tree_id, 'demo_v1', 1, 'leaf_ok',
            :kind, :status_code, :severity, 'Checked and fine.',
            now(), :valid_to, now()
        )
    """
    return sql, params


@pytest.mark.asyncio
async def test_0091_creates_the_names_its_downgrade_drops(admin_session: Any) -> None:
    schema = await _shared_schema(admin_session)
    await _use_schema(admin_session, schema)

    tables = (
        await admin_session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t)"
            ),
            {"s": schema, "t": _TABLE},
        )
    ).scalar_one()
    assert tables is True

    names = {
        str(r[0])
        for r in (
            await admin_session.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
                    "WHERE ns.nspname = :s AND rel.relname = :t"
                ),
                {"s": schema, "t": _TABLE},
            )
        ).all()
    }
    for constraint in _CONSTRAINTS:
        assert constraint in names, sorted(names)
    # The doubled spelling, which `op.create_check_constraint` produces when
    # it is handed a full name instead of a suffix.
    assert not any("ck_decision_tree_block_verdicts_ck_" in n for n in names)

    indexes = {
        str(r[0])
        for r in (
            await admin_session.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :t"),
                {"s": schema, "t": _TABLE},
            )
        ).all()
    }
    for index in _INDEXES:
        assert index in indexes, sorted(indexes)


@pytest.mark.asyncio
async def test_0091_rolls_back_and_forward(admin_session: Any) -> None:
    schema = await _new_tenant_schema(admin_session, "mig91rt")
    cfg = _alembic_cfg(schema)

    command.downgrade(cfg, "0090")
    await _use_schema(admin_session, schema)
    gone = (
        await admin_session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t)"
            ),
            {"s": schema, "t": _TABLE},
        )
    ).scalar_one()
    assert gone is False

    command.upgrade(cfg, "0091")
    await _use_schema(admin_session, schema)
    back = (
        await admin_session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t)"
            ),
            {"s": schema, "t": _TABLE},
        )
    ).scalar_one()
    assert back is True


@pytest.mark.asyncio
async def test_one_open_verdict_per_block_and_tree(admin_session: Any) -> None:
    """The COALESCE case: both rows have cell_id NULL."""
    schema = await _shared_schema(admin_session)
    await _use_schema(admin_session, schema)

    block_id, tree_id = str(uuid4()), str(uuid4())
    sql, params = _insert(block_id=block_id, tree_id=tree_id)
    await admin_session.execute(text(sql), params)
    await admin_session.commit()
    await _use_schema(admin_session, schema)

    sql, params = _insert(block_id=block_id, tree_id=tree_id, status_code="issue")
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()
    await _use_schema(admin_session, schema)

    # Closing the first one frees the slot. This is the write path's step:
    # set valid_to, then insert the new interval.
    await admin_session.execute(
        text(
            "UPDATE decision_tree_block_verdicts SET valid_to = now() "
            "WHERE block_id = :b AND tree_id = :t AND valid_to IS NULL"
        ),
        {"b": block_id, "t": tree_id},
    )
    sql, params = _insert(block_id=block_id, tree_id=tree_id, status_code="issue")
    await admin_session.execute(text(sql), params)
    await admin_session.commit()
    await _use_schema(admin_session, schema)

    open_rows = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM decision_tree_block_verdicts "
                "WHERE block_id = :b AND valid_to IS NULL"
            ),
            {"b": block_id},
        )
    ).scalar_one()
    assert open_rows == 1


@pytest.mark.asyncio
async def test_two_cells_of_one_block_are_not_in_conflict(admin_session: Any) -> None:
    schema = await _shared_schema(admin_session)
    await _use_schema(admin_session, schema)

    block_id, tree_id = str(uuid4()), str(uuid4())
    for _ in range(2):
        sql, params = _insert(
            block_id=block_id, tree_id=tree_id, cell_id=str(uuid4()), scope="cell"
        )
        await admin_session.execute(text(sql), params)
    await admin_session.commit()
    await _use_schema(admin_session, schema)

    rows = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM decision_tree_block_verdicts "
                "WHERE block_id = :b AND valid_to IS NULL"
            ),
            {"b": block_id},
        )
    ).scalar_one()
    assert rows == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"status_code": "gud"}, "a typo in a status reads as a legitimate verdict"),
        ({"kind": "verdict"}, "an unknown kind has no colour and no home"),
        ({"kind": "alert", "severity": None}, "a work item with no severity cannot be ranked"),
        ({"severity": "warning"}, "a status leaf carries no severity"),
        ({"cell_id": str(uuid4())}, "a cell id without cell scope"),
        ({"valid_to": "1990-01-01T00:00:00Z"}, "an interval that ends before it starts"),
    ],
)
async def test_the_checks_refuse_a_row_worse_stored_than_rejected(
    admin_session: Any, overrides: dict[str, Any], why: str
) -> None:
    schema = await _shared_schema(admin_session)
    await _use_schema(admin_session, schema)

    sql, params = _insert(**overrides)
    with pytest.raises(DBAPIError):
        await admin_session.execute(text(sql), params)
    await admin_session.rollback()
