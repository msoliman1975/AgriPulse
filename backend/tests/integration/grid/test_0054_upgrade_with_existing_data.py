"""Migration 0054 must survive a tenant that already has grid history.

Every other test creates its tenant fresh, so 0054 has only ever run
against an EMPTY ``grid_configs``, where the exclusion constraint is
trivially satisfiable. Production has blocks that have been rezoned, i.e.
retired configs sitting beside the live one for the same (block, product).

The backfill gives every row ``effective_from = '-infinity'`` and sets
``effective_to = retired_at`` only on retired rows. So a block rezoned
once yields ``[-infinity, T1)`` and ``[-infinity, NULL)`` — which overlap.

This test downgrades to 0053, seeds that shape, and upgrades again.
"""

from __future__ import annotations

import asyncio
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

_FARM = "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"


def _cfg(schema: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


async def _seed_rezoned_block(session: Any, schema: str) -> None:
    """A block whose grid has been rezoned once: one retired, one live."""
    farm_id, block_id = uuid4(), uuid4()
    product_id = (
        await session.execute(text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'"))
    ).scalar_one()

    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'MG', 'MG', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :f, 'MB', 'MB', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "f": str(farm_id), "b": _BLOCK},
    )
    retired_at = datetime.now(UTC) - timedelta(days=30)
    await session.execute(
        text(
            "INSERT INTO grid_configs "
            "(block_id, product_id, cell_size_m, utm_srid, retired_at) "
            "VALUES (:b, :p, 30, 32636, :r)"
        ).bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {"b": block_id, "p": UUID(str(product_id)), "r": retired_at},
    )
    await session.execute(
        text(
            "INSERT INTO grid_configs "
            "(block_id, product_id, cell_size_m, utm_srid) "
            "VALUES (:b, :p, 20, 32636)"
        ).bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {"b": block_id, "p": UUID(str(product_id))},
    )
    await session.commit()


async def test_0054_upgrades_a_tenant_that_has_already_rezoned(
    admin_session: Any,
) -> None:
    """The upgrade path production will actually take.

    Fails if the backfill leaves two live configs claiming overlapping
    scene-time ranges — which is what a rezone produces, since both rows
    start at ``-infinity``.
    """
    slug = f"mig54d-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    cfg = _cfg(schema)
    # Back to the world as it exists in production today.
    await asyncio.to_thread(command.downgrade, cfg, "0053")

    await _seed_rezoned_block(admin_session, schema)
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    # The real upgrade. Must not raise.
    await asyncio.to_thread(command.upgrade, cfg, "head")

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = (
        (
            await admin_session.execute(
                text(
                    "SELECT cell_size_m, retired_at, effective_from, effective_to "
                    "FROM grid_configs ORDER BY cell_size_m"
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 2
    live = next(r for r in rows if r["retired_at"] is None)
    old = next(r for r in rows if r["retired_at"] is not None)

    # The retired geometry governs up to its retirement; the live one takes
    # over from there. Anything else means history is either unreadable
    # (gap) or ambiguous (overlap).
    assert old["effective_to"] == old["retired_at"]
    assert live["effective_from"] == old["effective_to"], (
        "the live grid must start where the retired one stops — "
        f"got {live['effective_from']} vs {old['effective_to']}"
    )


async def _seed_chain(session: Any, schema: str, retire_times: list[datetime | None]) -> None:
    """One block whose grid was rezoned len(retire_times)-1 times."""
    farm_id, block_id = uuid4(), uuid4()
    product_id = (
        await session.execute(text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'"))
    ).scalar_one()
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'CH', 'CH', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :f, 'CB', 'CB', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "f": str(farm_id), "b": _BLOCK},
    )
    for i, r in enumerate(retire_times):
        await session.execute(
            text(
                "INSERT INTO grid_configs "
                "(block_id, product_id, cell_size_m, utm_srid, retired_at) "
                "VALUES (:b, :p, :cs, 32636, :r)"
            ).bindparams(
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"b": block_id, "p": UUID(str(product_id)), "cs": 60 - i * 10, "r": r},
        )
    await session.commit()


async def _upgrade_with(admin_session: Any, slug: str, retire_times: list[Any]) -> list[Any]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name
    await admin_session.commit()

    cfg = _cfg(schema)
    await asyncio.to_thread(command.downgrade, cfg, "0053")
    await _seed_chain(admin_session, schema, retire_times)
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    await asyncio.to_thread(command.upgrade, cfg, "head")

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    return list(
        (
            await admin_session.execute(
                text(
                    "SELECT cell_size_m, retired_at, effective_from, effective_to, "
                    "       superseded_at FROM grid_configs "
                    "ORDER BY retired_at ASC NULLS LAST"
                )
            )
        )
        .mappings()
        .all()
    )


async def test_0054_chains_several_rezones_without_gap_or_overlap(
    admin_session: Any,
) -> None:
    """Three rezones. Each geometry governs from the previous retirement."""
    now = datetime.now(UTC)
    t1, t2, t3 = now - timedelta(days=90), now - timedelta(days=60), now - timedelta(days=30)
    rows = await _upgrade_with(admin_session, f"mig54c-{uuid4().hex[:8]}", [t1, t2, t3, None])

    assert len(rows) == 4
    assert all(r["superseded_at"] is None for r in rows)
    # Oldest starts at -infinity; each subsequent starts where the last ended;
    # the live one is open-ended. Contiguous and non-overlapping.
    assert rows[0]["effective_to"] == t1
    for prev, cur in pairwise(rows):
        assert cur["effective_from"] == prev["effective_to"], "gap or overlap in the chain"
    assert rows[-1]["effective_to"] is None
    assert rows[-1]["retired_at"] is None


async def test_0054_tolerates_two_configs_retired_at_the_same_instant(
    admin_session: Any,
) -> None:
    """A degenerate row governed no scene time, so it is marked superseded.

    Giving it an empty range instead would violate the
    `effective_to > effective_from` check and fail the migration.
    """
    now = datetime.now(UTC)
    tie = now - timedelta(days=45)
    rows = await _upgrade_with(admin_session, f"mig54t-{uuid4().hex[:8]}", [tie, tie, None])

    assert len(rows) == 3
    superseded = [r for r in rows if r["superseded_at"] is not None]
    assert len(superseded) == 1, "the duplicate-instant config should govern nothing"
    live = next(r for r in rows if r["retired_at"] is None)
    assert live["effective_from"] == tie
    assert live["effective_to"] is None
