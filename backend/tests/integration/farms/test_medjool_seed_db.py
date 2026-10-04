"""The organic Medjool seed as the database holds it after public 0096-0099.

The unit tests check the literals. This checks the rows: that the old date
palm templates are gone, that Medjool is reachable (``date_palm`` at
``variety`` depth), and that the calendar, attributes, signals and templates
landed where the trees and the plan apply path look for them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.phenology import validate_phenology_payload

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_date_palm_is_at_variety_depth(admin_session: AsyncSession) -> None:
    depth = (
        await admin_session.execute(
            text("SELECT classification_depth FROM public.crops WHERE code = 'date_palm'")
        )
    ).scalar_one()
    assert depth == "variety"


@pytest.mark.asyncio
async def test_old_date_palm_templates_are_deleted(admin_session: AsyncSession) -> None:
    left = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.plan_templates WHERE code LIKE 'datepalm-%-eg'")
        )
    ).scalar_one()
    assert left == 0


@pytest.mark.asyncio
async def test_only_medjool_keeps_a_calendar(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                "SELECT v.code, v.phenology_stages_override FROM public.crop_varieties v "
                "JOIN public.crops c ON c.id = v.crop_id WHERE c.code = 'date_palm'"
            )
        )
    ).all()
    overrides = dict(rows)
    assert overrides["medjool"] is not None
    validate_phenology_payload(overrides["medjool"], is_perennial=True, has_gdd_base=False)
    assert [s["code"] for s in overrides["medjool"]["stages"]] == [
        "dormancy",
        "pollination",
        "fruit_set",
        "kimri",
        "khalal",
        "rutab",
        "tamar",
        "harvest",
        "post_harvest",
    ]
    assert all(pheno is None for code, pheno in overrides.items() if code != "medjool")
    # Public 0100: names from the manual's Arabic edition, section 12.2.
    names_ar = {s["code"]: s["name_ar"] for s in overrides["medjool"]["stages"]}
    assert names_ar["pollination"] == "ظهور الطلع والتلقيح"
    assert names_ar["post_harvest"] == "ما بعد الحصاد والزراعة الخريفية"


@pytest.mark.asyncio
async def test_medjool_attributes(admin_session: AsyncSession) -> None:
    codes = set(
        (
            await admin_session.execute(
                text(
                    "SELECT code FROM public.crop_attribute_definitions "
                    "WHERE path = 'date_palm.medjool' AND crop_variety_id IS NOT NULL"
                )
            )
        ).scalars()
    )
    assert codes == {
        "palm_phase",
        "tc_pinnate_leaves_at_planting",
        "nursery_rooting_months",
        "young_palm_protection",
        "organic_certified",
        "certifying_body",
    }


@pytest.mark.asyncio
async def test_medjool_signals_and_forms(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                "SELECT code, name_ar, categorical_values, categorical_values_ar "
                "FROM public.signal_definitions WHERE tenant_id IS NULL AND code LIKE 'date\\_%'"
            )
        )
    ).all()
    assert len(rows) == 15
    assert all(name_ar for _, name_ar, _, _ in rows)
    ripening = next(r for r in rows if r.code == "date_ripening_stage")
    assert ripening.categorical_values == ["khalal", "rutab", "tamar"]
    assert len(ripening.categorical_values_ar) == 3

    members = dict(
        (
            await admin_session.execute(
                text(
                    "SELECT t.code, count(*) FROM public.signal_templates t "
                    "JOIN public.signal_template_definitions d ON d.template_id = t.id "
                    "WHERE t.tenant_id IS NULL AND t.code LIKE 'medjool\\_%' GROUP BY t.code"
                )
            )
        ).all()
    )
    assert members == {"medjool_bearing": 13, "medjool_new_planting": 4}
    black_nose = next(r for r in rows if r.code == "date_black_nose_seen")
    assert black_nose.name_ar == "ظهور الذنب الأسود"


@pytest.mark.asyncio
async def test_medjool_templates(admin_session: AsyncSession) -> None:
    rows = dict(
        (
            await admin_session.execute(
                text(
                    "SELECT t.code, count(a.id) FROM public.plan_templates t "
                    "JOIN public.plan_template_activities a ON a.template_id = t.id "
                    "WHERE t.crop_path = 'date_palm.medjool' AND t.status = 'published' "
                    "GROUP BY t.code"
                )
            )
        ).all()
    )
    assert rows == {"medjool-organic-bearing-eg": 31, "medjool-organic-new-planting-eg": 20}
