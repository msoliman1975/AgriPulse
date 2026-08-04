"""Migration 0054 must survive downgrade and re-upgrade.

Constraint names rendered through a naming convention are the classic way
a downgrade breaks: the create side works, the drop side names something
that was never created, and the failure only shows up when someone tries
to roll back a bad deploy — the worst possible moment to discover it.
"""

from __future__ import annotations

import asyncio
from argparse import Namespace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def _alembic_cfg(schema: str) -> Config:
    """Same wiring ``TenantBootstrap._run_alembic_upgrade`` uses."""
    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


_OBJECTS = {
    "ex_grid_configs_no_overlap": "constraint",
    "ck_grid_configs_effective_range": "constraint",
}
_COLUMNS = ("effective_from", "effective_to", "superseded_at")


async def _columns(session: Any, schema: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'grid_configs'"
            ),
            {"s": schema},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _constraints(session: Any, schema: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
                "WHERE ns.nspname = :s AND rel.relname = 'grid_configs'"
            ),
            {"s": schema},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def test_0054_names_match_what_downgrade_drops(admin_session: Any) -> None:
    """The constraints exist under exactly the names ``downgrade()`` drops.

    Asserted against ``pg_constraint`` rather than by catching a violation,
    so a convention-doubled name (``ck_grid_configs_ck_grid_configs_...``)
    is caught here instead of at rollback time.
    """
    slug = f"mig54-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    cols = await _columns(admin_session, schema)
    assert set(_COLUMNS).issubset(cols), f"missing valid-time columns: {set(_COLUMNS) - cols}"

    cons = await _constraints(admin_session, schema)
    present = sorted(cons)
    for name in _OBJECTS:
        assert name in cons, f"{name!r} missing — downgrade() cannot drop it. Have: {present}"

    idx = (
        await admin_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = 'grid_configs'"
            ),
            {"s": schema},
        )
    ).all()
    assert "ix_grid_configs_superseded_at" in {str(r[0]) for r in idx}


async def test_0054_backfill_leaves_no_ungoverned_config(admin_session: Any) -> None:
    """Every live config governs *some* range after the migration.

    A config with no governing range is invisible to every read path — the
    exact failure this migration exists to remove. The upgrade backfill
    must not create one.
    """
    slug = f"mig54b-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    bad = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM grid_configs "
                "WHERE deleted_at IS NULL AND superseded_at IS NULL "
                "  AND effective_to IS NOT NULL "
                "  AND effective_to <= effective_from"
            )
        )
    ).scalar_one()
    assert bad == 0


async def test_0054_downgrade_then_upgrade_actually_runs(admin_session: Any) -> None:
    """Execute the rollback for real, then roll forward again.

    Name-matching (above) catches the common failure statically; this runs
    the SQL. A downgrade that only ever gets exercised during an incident
    is a downgrade nobody knows works.
    """
    slug = f"mig54rt-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    assert set(_COLUMNS).issubset(await _columns(admin_session, schema))

    cfg = _alembic_cfg(schema)
    # Alembic is synchronous and opens its own engine; keep it off the loop.
    await asyncio.to_thread(command.downgrade, cfg, "0053")

    after_down = await _columns(admin_session, schema)
    assert (
        not set(_COLUMNS) & after_down
    ), f"downgrade left valid-time columns behind: {set(_COLUMNS) & after_down}"
    cons_down = await _constraints(admin_session, schema)
    for name in _OBJECTS:
        assert name not in cons_down, f"downgrade left {name!r} behind"

    await asyncio.to_thread(command.upgrade, cfg, "head")

    assert set(_COLUMNS).issubset(await _columns(admin_session, schema))
    assert set(_OBJECTS).issubset(await _constraints(admin_session, schema))
