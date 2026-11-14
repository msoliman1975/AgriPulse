"""D18/D23 on Postgres: the seeded Medjool values resolve along the path."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.reference_values.router import view_for
from app.modules.sources.service import SourcesService


@pytest.mark.asyncio
async def test_medjool_inherits_salinity_and_sets_its_own_yield(admin_session: Any) -> None:
    view = await view_for(admin_session, "date_palm.medjool")
    resolved = view["resolved"]
    assert resolved["soil_ece_threshold_ds_m"]["value"] == Decimal("4.0")
    assert resolved["soil_ece_threshold_ds_m"]["from_path"] == "date_palm"
    assert resolved["yield_per_plant_kg"]["value_min"] == Decimal("60")
    assert resolved["yield_per_plant_kg"]["from_path"] == "date_palm.medjool"
    assert view["plants_per_ha"] == 123.5
    assert (await view_for(admin_session, "date_palm"))["plants_per_ha"] == 125.0

    links = await SourcesService(admin_session).links_for(
        entity_type="reference_value", entity_key="date_palm#soil_ece_threshold_ds_m"
    )
    assert [link["confidence"] for link in links] == ["high"]
