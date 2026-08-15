"""Integration test: public migration 0066 seeds the Landsat thermal catalog.

Public migrations run once at session start via the conftest's
`_wire_settings` fixture, so this only inspects the resulting state.

The assertions here are the ones that would silently degrade the product
if they drifted: the band list must exclude the quality band, the
supported-index list must name the three thermal indices, and LST's
bounds must be a temperature range rather than the [-1, 1] every other
index uses.

There is deliberately no downgrade test here. `test_seed_migration_
idempotent` in test_public_pgstac_and_catalog.py already downgrades the
whole public chain to 0007 and back up to head, so 0066's downgrade is
executed there with far better coverage than a hand-written check — and
a hand-written one has to take write locks on platform-wide catalog rows
that roughly 800 other tests read.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_landsat_provider_seeded(admin_session: AsyncSession) -> None:
    row = (
        await admin_session.execute(
            text(
                "SELECT code, name, kind, config_schema "
                "FROM public.imagery_providers WHERE code = 'landsat_pc'"
            )
        )
    ).one()

    assert row.code == "landsat_pc"
    # Open data we retrieve and process ourselves, unlike Sentinel Hub's
    # `commercial_api` where the provider does the processing.
    assert row.kind == "open_self_managed"
    # No credential fields: Planetary Computer is anonymous.
    assert set(row.config_schema["properties"]) == {"stac_url", "sas_url"}


@pytest.mark.asyncio
async def test_thermal_product_seeded(admin_session: AsyncSession) -> None:
    row = (
        await admin_session.execute(
            text(
                """
                SELECT p.code, p.resolution_m, p.revisit_days_avg,
                       p.bands, p.supported_indices, p.cost_tier
                  FROM public.imagery_products p
                  JOIN public.imagery_providers pr ON pr.id = p.provider_id
                 WHERE p.code = 'landsat_c2_l2_st' AND pr.code = 'landsat_pc'
                """
            )
        )
    ).one()

    assert float(row.resolution_m) == 30.0
    assert float(row.revisit_days_avg) == 8.0
    # First free row in the catalog.
    assert row.cost_tier == "free"

    # Science bands only. `qa_pixel` is a quality band and rides as a
    # trailing band the way SCL does for Sentinel-2 — migration 0027 put
    # `ndmi` in `bands` by mistake and needed 0029 to undo it, so this
    # distinction is load-bearing: a quality band listed here would make
    # the COG reader expect one more science band than it gets.
    assert list(row.bands) == ["lwir11", "red", "nir08"]
    assert "qa_pixel" not in row.bands

    assert sorted(row.supported_indices) == ["cwsi", "lst", "smi"]


@pytest.mark.asyncio
async def test_thermal_indices_seeded(admin_session: AsyncSession) -> None:
    rows = {
        r.code: r
        for r in (
            await admin_session.execute(
                text(
                    "SELECT code, name_en, name_ar, value_min, value_max, is_standard "
                    "FROM public.indices_catalog "
                    "WHERE code IN ('lst','cwsi','smi')"
                )
            )
        ).all()
    }

    assert set(rows) == {"lst", "cwsi", "smi"}
    for row in rows.values():
        assert row.is_standard is True
        assert row.name_ar, f"{row.code} must carry an Arabic name"

    # LST is the first index in the catalog with a unit. Its bounds are
    # degrees Celsius, not the dimensionless [-1, 1] every other row
    # uses, so anything that assumes that range renders it as a flat
    # line pinned to the axis top.
    assert float(rows["lst"].value_min) == 0.0
    assert float(rows["lst"].value_max) == 60.0

    # Both derived indices are 0-1 by construction.
    for code in ("cwsi", "smi"):
        assert float(rows[code].value_min) == 0.0
        assert float(rows[code].value_max) == 1.0


@pytest.mark.asyncio
async def test_thermal_seed_does_not_create_subscriptions(
    admin_session: AsyncSession,
) -> None:
    """Seeding the catalog must not start fetching for anyone.

    `imagery_farm_subscriptions` is unique on (farm_id, product_id), so a
    thermal subscription coexists with the Sentinel-2 one rather than
    replacing it — but opting a farm in is a deliberate operational step,
    mirroring how `fetch_farm_aoi` defaults FALSE.
    """
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 'landsat_c2_l2_st'")
        )
    ).scalar_one()

    # Tenant tables live in per-tenant schemas; check none of them
    # reference the new product.
    schemas = [
        r[0]
        for r in (
            await admin_session.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE 'tenant_%'"
                )
            )
        ).all()
    ]
    for schema in schemas:
        count = (
            await admin_session.execute(
                text(
                    # Schema name comes from information_schema, not user input.
                    f"SELECT count(*) FROM {schema}.imagery_farm_subscriptions "
                    "WHERE product_id = :pid"
                ),
                {"pid": product_id},
            )
        ).scalar_one()
        assert count == 0, f"{schema} unexpectedly subscribed to the thermal product"
