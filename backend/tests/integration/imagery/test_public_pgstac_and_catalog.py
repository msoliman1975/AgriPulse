"""Integration test: public migrations 0007 + 0008 land pgstac, catalogs, seeds.

Public migrations are run once at session start by the conftest's
`_wire_settings` fixture, so this test only inspects the resulting
state — no further migration calls are made here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_pgstac_schema_present(admin_session: AsyncSession) -> None:
    """pgstac was bootstrapped via pypgstac (Q1 in the PR-A plan).

    pypgstac creates a `pgstac` schema and at least the `items` and
    `collections` tables — exact counts vary by version, but those
    two are stable contracts.
    """
    schema_count = (
        await admin_session.execute(
            text("SELECT count(*) FROM information_schema.schemata " "WHERE schema_name = 'pgstac'")
        )
    ).scalar_one()
    assert schema_count == 1

    table_names = {
        row[0]
        for row in (
            await admin_session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'pgstac'"
                )
            )
        ).all()
    }
    assert {"items", "collections"}.issubset(table_names)


@pytest.mark.asyncio
async def test_catalog_tables_present(admin_session: AsyncSession) -> None:
    table_names = {
        row[0]
        for row in (
            await admin_session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN ("
                    "'imagery_providers','imagery_products','indices_catalog')"
                )
            )
        ).all()
    }
    assert table_names == {"imagery_providers", "imagery_products", "indices_catalog"}


@pytest.mark.asyncio
async def test_sentinel_hub_provider_seeded(admin_session: AsyncSession) -> None:
    row = (
        await admin_session.execute(
            text(
                "SELECT code, kind, is_active "
                "FROM public.imagery_providers WHERE code = 'sentinel_hub'"
            )
        )
    ).one()
    assert row.code == "sentinel_hub"
    assert row.kind == "commercial_api"
    assert row.is_active is True


@pytest.mark.asyncio
async def test_s2_l2a_product_seeded_with_correct_bands(
    admin_session: AsyncSession,
) -> None:
    row = (
        await admin_session.execute(
            text(
                "SELECT code, resolution_m, bands, supported_indices, cost_tier "
                "FROM public.imagery_products WHERE code = 's2_l2a'"
            )
        )
    ).one()
    assert row.code == "s2_l2a"
    assert float(row.resolution_m) == 10.0
    assert row.bands == [
        "blue",
        "green",
        "red",
        "red_edge_1",
        "nir",
        "swir1",
        "swir2",
    ]
    assert set(row.supported_indices) == {
        "ndvi",
        "ndwi",
        "evi",
        "savi",
        "ndre",
        "gndvi",
        # ndmi advertised on s2_l2a (0027 + 0029 correction).
        "ndmi",
        # bsi + msi from the indices-guide gap audit (0061). Both land in
        # `supported_indices` and NOT in `bands` above — the mistake 0027 made
        # and 0029 had to undo.
        "bsi",
        "msi",
        # msavi (0068) — same RED/NIR pair savi already reads, so no band
        # change came with it either.
        "msavi",
    }
    assert row.cost_tier == "medium"


@pytest.mark.asyncio
async def test_standard_indices_seeded(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                "SELECT code, name_en, name_ar, value_min, value_max, is_standard "
                "FROM public.indices_catalog ORDER BY code"
            )
        )
    ).all()
    codes = [r.code for r in rows]
    # ndmi added by 0027 (KB P2 moisture index); bsi + msi by 0061 (gap
    # audit); cwsi + lst + smi by 0066 (the thermal gap, a different
    # product entirely); msavi by 0068. Sorted by code, so the three thermal
    # ones scatter through the list rather than trailing it.
    assert codes == [
        "bsi",
        "cwsi",
        "evi",
        "gndvi",
        "lst",
        "msavi",
        "msi",
        "ndmi",
        "ndre",
        "ndvi",
        "ndwi",
        "savi",
        "smi",
    ]
    for r in rows:
        assert r.is_standard is True
        assert r.name_en  # non-empty English label
        assert r.name_ar  # non-empty Arabic label

    # Every normalized-difference index shares the [-1, 1] range. `msi` does
    # not, and that is the point of it: it is a plain SWIR/NIR ratio, so a
    # blanket bounds assertion here would have to be relaxed into meaning
    # nothing. Assert the families separately instead.
    by_code = {r.code: r for r in rows}
    for code in ("bsi", "evi", "gndvi", "msavi", "ndmi", "ndre", "ndvi", "ndwi", "savi"):
        assert float(by_code[code].value_min) == -1.0, code
        assert float(by_code[code].value_max) == 1.0, code
    assert float(by_code["msi"].value_min) == 0.0
    assert float(by_code["msi"].value_max) == 3.0

    # The thermal family (0066). `lst` is the first index in this catalog
    # carrying a UNIT: its bounds are degrees Celsius, not a ratio, so
    # anything that assumes [-1, 1] renders it as a flat line pinned to
    # the top of the axis. `cwsi` and `smi` are 0-1 by construction.
    assert float(by_code["lst"].value_min) == 0.0
    assert float(by_code["lst"].value_max) == 60.0
    for code in ("cwsi", "smi"):
        assert float(by_code[code].value_min) == 0.0, code
        assert float(by_code[code].value_max) == 1.0, code


@pytest.mark.asyncio
async def test_seed_migration_idempotent(admin_session: AsyncSession) -> None:
    """Re-running 0008 must not duplicate rows (ON CONFLICT DO NOTHING)."""
    # Just count and assert stable.
    count_before = (
        await admin_session.execute(text("SELECT count(*) FROM public.indices_catalog"))
    ).scalar_one()

    # Release this session's read transaction BEFORE running migrations on
    # another connection. The SELECT above leaves an open transaction
    # holding ACCESS SHARE on `indices_catalog`; any downgrade in the chain
    # that does DDL on that table needs ACCESS EXCLUSIVE and will wait on
    # it forever. Public 0067 (`ALTER TABLE ... DROP COLUMN unit`) is the
    # first such migration, and it hung CI for the full job timeout with
    # no error — a lock wait looks exactly like a slow test.
    await admin_session.rollback()

    # Reapply by running the seed SQL paths that 0008 issues.
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend_root / "alembic.ini"), ini_section="public")
    # Downgrade past 0008's seeds, then re-apply everything up to head so
    # later tests don't see a partially-migrated DB. The finally guarantees
    # restoration even if the downgrade raises partway — the DB is
    # session-shared, so a half-applied downgrade would poison every later
    # test. Upgrading to "head" keeps this order-independent as new
    # migrations land in the public chain.
    try:
        command.downgrade(cfg, "0007")
    finally:
        command.upgrade(cfg, "head")

    count_after = (
        await admin_session.execute(text("SELECT count(*) FROM public.indices_catalog"))
    ).scalar_one()
    assert count_after == count_before
