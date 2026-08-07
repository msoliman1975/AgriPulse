"""Migration 0059 must survive downgrade and re-upgrade.

Named constraints and indexes are the classic way a downgrade breaks: the
create side works, the drop side names something that was never created, and
the failure only surfaces when someone tries to roll back a bad deploy — the
worst possible moment to find out. Convention-doubled names
(``ck_indices_calc_runs_ck_indices_calc_runs_…``) have bitten this repo
before, so the names are asserted against the catalog rather than inferred.
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

from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

_CONSTRAINTS = (
    "ck_indices_calc_runs_trigger",
    "ck_indices_calc_runs_outcome",
    "ck_indices_calc_runs_masked_within_aoi",
)
_INDEXES = (
    "ix_indices_calc_runs_scene",
    "ix_indices_calc_runs_version_window",
)


def _alembic_cfg(schema: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


async def _constraint_names(session: Any, schema: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
                "WHERE ns.nspname = :s AND rel.relname = 'indices_calc_runs'"
            ),
            {"s": schema},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _index_names(session: Any, schema: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = 'indices_calc_runs'"
            ),
            {"s": schema},
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _table_exists(session: Any, schema: str) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = 'indices_calc_runs')"
                ),
                {"s": schema},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_0059_creates_the_names_downgrade_drops(admin_session: Any) -> None:
    slug = f"mig59-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    assert await _table_exists(admin_session, schema)

    cons = await _constraint_names(admin_session, schema)
    for name in _CONSTRAINTS:
        assert name in cons, f"{name!r} missing — have {sorted(cons)}"

    idx = await _index_names(admin_session, schema)
    for name in _INDEXES:
        assert name in idx, f"{name!r} missing — have {sorted(idx)}"


@pytest.mark.asyncio
async def test_0059_round_trips(admin_session: Any) -> None:
    """down to 0057, back up to head, and the table is whole again."""
    slug = f"mig59r-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    cfg = _alembic_cfg(schema)
    command.downgrade(cfg, "0058")
    assert not await _table_exists(admin_session, schema)

    command.upgrade(cfg, "head")
    assert await _table_exists(admin_session, schema)
    assert set(_INDEXES) <= await _index_names(admin_session, schema)


@pytest.mark.asyncio
async def test_the_trigger_and_outcome_vocabularies_are_enforced(
    admin_session: Any,
) -> None:
    """The CHECKs are the reason a bad `trigger` cannot reach Observer.

    Without them a typo'd trigger would sit in the lineage table and read as
    a legitimate provenance, which is worse than a write that fails loudly.
    """
    from sqlalchemy.exc import DBAPIError

    slug = f"mig59c-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

    insert = text(
        """
        INSERT INTO indices_calc_runs (
            scene_time, scene_id, block_id, product_id,
            calc_version, mask_ruleset, trigger
        ) VALUES (
            now(), 'S2A_X', gen_random_uuid(), gen_random_uuid(),
            'idx-test', 's2_scl_v1', :trigger
        )
        """
    )
    with pytest.raises(DBAPIError):
        await admin_session.execute(insert, {"trigger": "definitely_not_a_trigger"})
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_masked_pixels_cannot_exceed_the_aoi_footprint(admin_session: Any) -> None:
    """A masked count above the footprint would make the budget unreconcilable."""
    from sqlalchemy.exc import DBAPIError

    slug = f"mig59m-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

    with pytest.raises(DBAPIError):
        await admin_session.execute(
            text(
                """
                INSERT INTO indices_calc_runs (
                    scene_time, scene_id, block_id, product_id,
                    calc_version, mask_ruleset,
                    aoi_pixel_count, masked_pixel_count
                ) VALUES (
                    now(), 'S2A_X', gen_random_uuid(), gen_random_uuid(),
                    'idx-test', 's2_scl_v1', 100, 101
                )
                """
            )
        )
    await admin_session.rollback()
