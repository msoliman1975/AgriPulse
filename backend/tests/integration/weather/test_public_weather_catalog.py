"""Integration test: public migrations 0009 + 0010 land weather catalogs + seeds.

Public migrations are run once at session start by the conftest's
`_wire_settings` fixture, so this test only inspects the resulting
state — no further migration calls are made here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_weather_catalog_tables_present(admin_session: AsyncSession) -> None:
    table_names = {
        row[0]
        for row in (
            await admin_session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN ("
                    "'weather_providers','weather_derived_signals_catalog')"
                )
            )
        ).all()
    }
    assert table_names == {"weather_providers", "weather_derived_signals_catalog"}


@pytest.mark.asyncio
async def test_open_meteo_provider_seeded(admin_session: AsyncSession) -> None:
    row = (
        await admin_session.execute(
            text(
                "SELECT code, kind, is_active "
                "FROM public.weather_providers WHERE code = 'open_meteo'"
            )
        )
    ).one()
    assert row.code == "open_meteo"
    assert row.kind == "open_api"
    assert row.is_active is True


@pytest.mark.asyncio
async def test_six_derived_signals_seeded(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                "SELECT code, name_en, name_ar, unit, is_active "
                "FROM public.weather_derived_signals_catalog ORDER BY code"
            )
        )
    ).all()
    codes = [r.code for r in rows]
    assert codes == [
        "et0_mm_daily",
        "gdd_base10",
        "gdd_base15",
        "gdd_cumulative_base10_season",
        "precip_mm_30d",
        "precip_mm_7d",
    ]
    for r in rows:
        assert r.is_active is True
        assert r.name_en
        assert r.name_ar
        assert r.unit


@pytest.mark.asyncio
async def test_weather_provider_kind_check_constraint(admin_session: AsyncSession) -> None:
    """ck_weather_providers_kind rejects values outside the allowlist."""
    with pytest.raises(IntegrityError, match="ck_weather_providers_kind"):
        await admin_session.execute(
            text(
                "INSERT INTO public.weather_providers (code, name, kind) "
                "VALUES ('bogus', 'Bogus', 'not_a_kind')"
            )
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_seed_migration_idempotent(admin_session: AsyncSession) -> None:
    """Re-running 0010 must not duplicate rows (ON CONFLICT DO NOTHING)."""
    count_before = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.weather_derived_signals_catalog")
        )
    ).scalar_one()

    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend_root / "alembic.ini"), ini_section="public")
    # Upgrade to "head" (not "0010") so later tests don't see a
    # partially-migrated DB once more migrations land after this one.
    command.downgrade(cfg, "0009")
    command.upgrade(cfg, "head")

    count_after = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.weather_derived_signals_catalog")
        )
    ).scalar_one()
    assert count_after == count_before
