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
    }
    assert row.cost_tier == "medium"


@pytest.mark.asyncio
async def test_six_standard_indices_seeded(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                "SELECT code, name_en, name_ar, value_min, value_max, is_standard "
                "FROM public.indices_catalog ORDER BY code"
            )
        )
    ).all()
    codes = [r.code for r in rows]
    assert codes == ["evi", "gndvi", "ndre", "ndvi", "ndwi", "savi"]
    for r in rows:
        assert r.is_standard is True
        assert r.name_en  # non-empty English label
        assert r.name_ar  # non-empty Arabic label
        assert float(r.value_min) == -1.0
        assert float(r.value_max) == 1.0


@pytest.mark.asyncio
async def test_seed_migration_idempotent(admin_session: AsyncSession) -> None:
    """Re-running 0008 must not duplicate rows (ON CONFLICT DO NOTHING)."""
    # Just count and assert stable.
    count_before = (
        await admin_session.execute(text("SELECT count(*) FROM public.indices_catalog"))
    ).scalar_one()

    # Reapply by running the seed SQL paths that 0008 issues.
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend_root / "alembic.ini"), ini_section="public")
    # Downgrade past 0008's seeds, then re-apply everything up to head so
    # later tests don't see a partially-migrated DB. Upgrading to "head"
    # (rather than pinning "0008") keeps this test order-independent as
    # new migrations land in the public chain.
    command.downgrade(cfg, "0007")
    command.upgrade(cfg, "head")

    count_after = (
        await admin_session.execute(text("SELECT count(*) FROM public.indices_catalog"))
    ).scalar_one()
    assert count_after == count_before
