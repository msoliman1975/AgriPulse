"""The seeded attribute catalog must satisfy the rules the API enforces.

Migration 0051 writes rows with raw SQL, so it bypasses every service-layer
guard. A seed that a platform admin could not have authored through the API is
a seed whose gates never open or whose form never validates — and neither
failure raises anything at render time. These tests re-apply the guards to the
rows as they actually landed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.crop_attributes import (
    GATEABLE_VALUE_TYPES,
    RESERVED_ATTRIBUTE_CODES,
    resolve_definitions,
    validate_type_consistency,
)

pytestmark = [pytest.mark.integration]

_SEEDED_CROPS = ("mango", "citrus_orange", "citrus_mandarin", "date_palm", "potato", "tomato")


class _Row:
    """Duck-typed stand-in so the pure resolver can walk raw DB rows."""

    def __init__(self, mapping: dict) -> None:
        self.__dict__.update(mapping)


async def _seeded(session: AsyncSession) -> list[_Row]:
    rows = (
        await session.execute(
            text(
                "SELECT path, code, name_en, name_ar, value_type, unit_en, unit_ar,"
                " value_min, value_max, decimal_places, text_max_length, options,"
                " is_required, required_when, show_when, group_code, sort_order,"
                " is_reportable, is_active"
                " FROM public.crop_attribute_definitions"
                " WHERE split_part(path, '.', 1) = ANY(:crops)"
                " ORDER BY path, sort_order"
            ),
            {"crops": list(_SEEDED_CROPS)},
        )
    ).mappings()
    return [_Row(dict(r)) for r in rows]


@pytest.mark.asyncio
async def test_seed_covers_the_documented_crops(admin_session: AsyncSession) -> None:
    rows = await _seeded(admin_session)
    assert rows, "migration 0051 seeded nothing — the feature has no catalog data"
    paths = {r.path for r in rows}
    for crop in _SEEDED_CROPS:
        assert crop in paths, f"{crop} has no crop-level attributes"
    # All three taxonomy depths, so deepest-wins is exercised by real data.
    assert "mango.sukkary" in paths
    assert "mango.alphonso.short" in paths


@pytest.mark.asyncio
async def test_no_seeded_code_shadows_a_first_class_block_field(
    admin_session: AsyncSession,
) -> None:
    for row in await _seeded(admin_session):
        assert row.code not in RESERVED_ATTRIBUTE_CODES, (
            f"{row.path}.{row.code} shadows a first-class block field — it would "
            "appear twice in the decision-tree condition builder"
        )


@pytest.mark.asyncio
async def test_every_seeded_definition_is_internally_consistent(
    admin_session: AsyncSession,
) -> None:
    """Same validator the create endpoint runs, applied to the seeded rows."""
    for row in await _seeded(admin_session):
        validate_type_consistency(
            value_type=row.value_type,
            options=row.options,
            value_min=row.value_min,
            value_max=row.value_max,
            decimal_places=row.decimal_places,
            unit_en=row.unit_en,
            unit_ar=row.unit_ar,
            text_max_length=row.text_max_length,
        )


@pytest.mark.asyncio
async def test_every_seeded_gate_points_at_a_usable_earlier_field(
    admin_session: AsyncSession,
) -> None:
    """A gate whose target is missing, non-gateable or later-sorted never opens
    — the field simply vanishes from every assignment, silently."""
    rows = await _seeded(admin_session)
    for row in rows:
        for field_name in ("show_when", "required_when"):
            gate = getattr(row, field_name)
            if not gate:
                continue
            resolved = {
                d.code: d for d in resolve_definitions(rows, crop_path=row.path).definitions
            }
            target = resolved.get(gate["code"])
            assert target is not None, f"{row.path}.{row.code}.{field_name} → missing target"
            assert target.value_type in GATEABLE_VALUE_TYPES, (
                f"{row.path}.{row.code}.{field_name} targets a "
                f"{target.value_type}, which cannot gate"
            )
            assert (
                target.sort_order < row.sort_order
            ), f"{row.path}.{row.code}.{field_name} targets a later-authored field"
            option_codes = {o["code"] for o in (target.options or [])}
            if target.value_type == "single_select":
                unknown = [v for v in gate.get("in", []) if v not in option_codes]
                assert not unknown, (
                    f"{row.path}.{row.code}.{field_name} tests {unknown!r}, "
                    f"which are not options of {target.code}"
                )


@pytest.mark.asyncio
async def test_seed_is_fully_bilingual(admin_session: AsyncSession) -> None:
    """A label or option that exists in one language only renders as English
    inside an otherwise-Arabic form."""
    for row in await _seeded(admin_session):
        assert row.name_en, f"{row.path}.{row.code} has no English name"
        assert row.name_ar, f"{row.path}.{row.code} has no Arabic name"
        assert (row.unit_en is None) == (row.unit_ar is None)
        for option in row.options or []:
            where = f"{row.path}.{row.code} option {option.get('code')!r}"
            assert option.get("name_en"), f"{where} has no English name"
            assert option.get("name_ar"), f"{where} has no Arabic name"


@pytest.mark.asyncio
async def test_deepest_wins_over_the_real_seed(admin_session: AsyncSession) -> None:
    """The two overrides the seed exists to demonstrate."""
    rows = await _seeded(admin_session)

    crop_level = {d.code: d for d in resolve_definitions(rows, crop_path="mango").definitions}
    assert float(crop_level["transplant_height_cm"].value_max) == 2000
    assert len(crop_level["rootstock_type"].options) == 4

    # Variety narrows the rootstock list; Sukkary goes on its own seedling.
    sukkary = {d.code: d for d in resolve_definitions(rows, crop_path="mango.sukkary").definitions}
    assert [o["code"] for o in sukkary["rootstock_type"].options] == [
        "sukkary_seedling",
        "local_polyembryonic",
    ]
    # ...and inherits everything it did not override.
    assert float(sukkary["transplant_height_cm"].value_max) == 2000

    # Strain narrows the height range.
    short = {
        d.code: d for d in resolve_definitions(rows, crop_path="mango.alphonso.short").definitions
    }
    assert float(short["transplant_height_cm"].value_max) == 250
    assert len(short["rootstock_type"].options) == 4  # unaffected by the sukkary override


@pytest.mark.asyncio
async def test_date_palm_is_not_grafted(admin_session: AsyncSession) -> None:
    """The point of seeding five crops: the concept transfers, the fields don't."""
    rows = await _seeded(admin_session)
    palm = {d.code for d in resolve_definitions(rows, crop_path="date_palm").definitions}
    assert "propagation_source" in palm
    assert "offshoot_age_months" in palm
    assert "rootstock_type" not in palm
    assert "establishment_method" not in palm

    potato = {d.code for d in resolve_definitions(rows, crop_path="potato").definitions}
    assert "seed_tuber_grade" in potato
    assert potato.isdisjoint(palm)
