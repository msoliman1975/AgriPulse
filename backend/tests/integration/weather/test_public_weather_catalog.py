"""Integration test: public migrations 0009/0010 + 0037 land weather catalogs + seeds.

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
async def test_weather_indices_catalog_present_and_seeded(admin_session: AsyncSession) -> None:
    """The catalog is append-only, and each migration proves it.

    0037 lands the table with 7 indices; 0049 appends `humidity` at 8; 0057
    the gap-audit trio at 9-11; 0065 `drought_spi` at 12. Every one of them
    leaves the earlier rows' sort_order untouched, which is what keeps the
    summary strip's ordering stable as the catalog grows."""
    present = (
        await admin_session.execute(
            text("SELECT to_regclass('public.weather_indices_catalog') IS NOT NULL")
        )
    ).scalar_one()
    assert present is True

    expected = [
        "temperature",
        "radiation",
        "wind",
        "rainfall",
        "evapotranspiration",
        "evaporation_coeff",
        "rain_et_balance",
        "humidity",
        # 0062, appended at 9-11 by the indices-guide gap audit.
        "leaf_wetness",
        "frost_risk",
        "heat_stress",
        "drought_spi",
    ]
    # Scope to the seeded codes — the DB is session-shared and other tests
    # (the endpoint test) commit extra rows into this table.
    rows = (
        await admin_session.execute(
            text(
                "SELECT code, name_en, name_ar, unit, source_kind, sort_order, is_active "
                "FROM public.weather_indices_catalog "
                "WHERE code = ANY(:codes) ORDER BY sort_order"
            ),
            {"codes": expected},
        )
    ).all()
    codes = [r.code for r in rows]
    assert codes == expected
    by_code = {r.code: r for r in rows}
    # The two derived indices carry source_kind='derived'; the rest observed.
    assert by_code["evaporation_coeff"].source_kind == "derived"
    assert by_code["rain_et_balance"].source_kind == "derived"
    assert by_code["temperature"].source_kind == "observed"
    assert by_code["humidity"].source_kind == "observed"
    assert by_code["humidity"].unit == "%"
    assert by_code["humidity"].sort_order == 8
    # The gap-audit trio are all derived, appended after humidity so the
    # existing rows keep their positions on the strip.
    for code, order in (("leaf_wetness", 9), ("frost_risk", 10), ("heat_stress", 11)):
        assert by_code[code].source_kind == "derived", code
        assert by_code[code].sort_order == order, code
    assert by_code["leaf_wetness"].unit == "h"
    for r in rows:
        assert r.is_active is True
        assert r.name_en
        assert r.name_ar
        assert r.unit


@pytest.mark.asyncio
async def test_weather_indices_catalog_source_kind_check(admin_session: AsyncSession) -> None:
    """ck_weather_indices_catalog_source_kind rejects values off the allowlist."""
    with pytest.raises(IntegrityError, match="ck_weather_indices_catalog_source_kind"):
        await admin_session.execute(
            text(
                "INSERT INTO public.weather_indices_catalog (code, name_en, unit, source_kind) "
                "VALUES ('bogus_idx', 'Bogus', 'mm', 'not_a_kind')"
            )
        )
    await admin_session.rollback()


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
    # Always restore to head, even if the downgrade raises partway — the DB is
    # session-shared, so a half-applied downgrade would poison every later
    # test (e.g. dropping tenants.suspended_at). The finally guarantees the
    # schema is whole again regardless of this test's own pass/fail.
    try:
        command.downgrade(cfg, "0009")
    finally:
        command.upgrade(cfg, "head")

    count_after = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.weather_derived_signals_catalog")
        )
    ).scalar_one()
    assert count_after == count_before
