"""Backfilling a country on farms that have none, against a real tenant schema.

Only farms with no country are set; a farm that names one keeps it. Each
farm gets the usual ``farms.farm_updated`` audit row, and the run gets one
``farms.country_backfilled`` row naming every farm it set.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.farms.service import get_farm_service
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


async def _farm(session: Any, code: str, country: str | None) -> Any:
    return (
        await session.execute(
            text(
                """
                INSERT INTO farms (
                    code, name, country_code, boundary, boundary_utm, centroid, area_m2
                ) VALUES (
                    :code, :code, :country,
                    ST_GeomFromText(:poly, 4326),
                    ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                    ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000
                ) RETURNING id
                """
            ),
            {"code": code, "country": country, "poly": _POLY},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_backfill_sets_only_empty_countries_and_audits(admin_session: Any) -> None:
    slug = f"bfc-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    await admin_session.commit()
    schema = str(tenant.schema_name)
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    empty_a = await _farm(admin_session, "BF-A", None)
    empty_b = await _farm(admin_session, "BF-B", None)
    saudi = await _farm(admin_session, "BF-SA", "SA")
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    service = get_farm_service(tenant_session=admin_session, public_session=admin_session)

    async def countries() -> dict[Any, Any]:
        rows = (await admin_session.execute(text("SELECT id, country_code FROM farms"))).all()
        return {r[0]: r[1] for r in rows}

    dry = await service.backfill_farm_country(
        country_code="EG", dry_run=True, actor_user_id=None, tenant_schema=schema
    )
    assert dry["count"] == 2
    assert {f["farm_id"] for f in dry["farms"]} == {empty_a, empty_b}
    assert (await countries())[empty_a] is None, "a dry run writes nothing"

    done = await service.backfill_farm_country(
        country_code="EG", dry_run=False, actor_user_id=None, tenant_schema=schema
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    assert done["count"] == 2
    after = await countries()
    assert after[empty_a] == "EG"
    assert after[empty_b] == "EG"
    assert after[saudi] == "SA", "a farm that names a country keeps it"

    summary = (
        await admin_session.execute(
            text(
                "SELECT details FROM audit_events "
                "WHERE event_type = 'farms.country_backfilled' ORDER BY time DESC LIMIT 1"
            )
        )
    ).scalar_one()
    assert summary["count"] == 2
    assert set(summary["farm_ids"]) == {str(empty_a), str(empty_b)}
    per_farm = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE event_type = 'farms.farm_updated' AND farm_id IN (:a, :b)"
            ),
            {"a": empty_a, "b": empty_b},
        )
    ).scalar_one()
    assert per_farm == 2

    again = await service.backfill_farm_country(
        country_code="EG", dry_run=False, actor_user_id=None, tenant_schema=schema
    )
    assert again["count"] == 0, "running it again finds nothing left to set"
