"""Seed the ~22 Egyptian crops in `public.crops`.

Idempotent: ON CONFLICT (code) DO NOTHING. Re-running this migration on a
schema that already contains seeded rows is a no-op.

The list mirrors the candidates documented in
`prompts/prompt_02_farm_management.md`. GDD bases come from FAO and ICARDA
references for arid-region cultivation; refine in a follow-up if a crop's
phenology model needs different defaults.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, name_en, name_ar, scientific_name, category, is_perennial,
#  growing_season_days, gdd_base_c, gdd_upper_c, relevant_indices)
_CROPS: tuple[
    tuple[
        str,
        str,
        str,
        str | None,
        str,
        bool,
        int | None,
        float | None,
        float | None,
        tuple[str, ...],
    ],
    ...,
] = (
    (
        "wheat",
        "Wheat",
        "قمح",
        "Triticum aestivum",
        "cereal",
        False,
        150,
        0.0,
        30.0,
        ("ndvi", "ndre"),
    ),
    ("maize", "Maize", "ذرة شامية", "Zea mays", "cereal", False, 110, 10.0, 30.0, ("ndvi", "ndre")),
    ("rice", "Rice", "أرز", "Oryza sativa", "cereal", False, 130, 10.0, 35.0, ("ndvi", "ndwi")),
    (
        "sugarcane",
        "Sugarcane",
        "قصب السكر",
        "Saccharum officinarum",
        "sugar",
        True,
        None,
        18.0,
        35.0,
        ("ndvi", "ndwi"),
    ),
    (
        "sugar_beet",
        "Sugar Beet",
        "بنجر السكر",
        "Beta vulgaris",
        "sugar",
        False,
        200,
        5.0,
        28.0,
        ("ndvi",),
    ),
    (
        "cotton",
        "Cotton",
        "قطن",
        "Gossypium hirsutum",
        "fiber",
        False,
        180,
        15.5,
        35.0,
        ("ndvi", "ndre"),
    ),
    (
        "soybean",
        "Soybean",
        "فول الصويا",
        "Glycine max",
        "legume",
        False,
        120,
        10.0,
        30.0,
        ("ndvi",),
    ),
    (
        "peanut",
        "Peanut",
        "فول سوداني",
        "Arachis hypogaea",
        "legume",
        False,
        130,
        13.0,
        30.0,
        ("ndvi",),
    ),
    (
        "sunflower",
        "Sunflower",
        "عباد الشمس",
        "Helianthus annuus",
        "oilseed",
        False,
        110,
        6.0,
        30.0,
        ("ndvi",),
    ),
    ("sesame", "Sesame", "سمسم", "Sesamum indicum", "oilseed", False, 100, 15.0, 35.0, ("ndvi",)),
    (
        "alfalfa",
        "Alfalfa",
        "برسيم حجازي",
        "Medicago sativa",
        "fodder",
        True,
        None,
        5.0,
        30.0,
        ("ndvi",),
    ),
    (
        "egyptian_clover",
        "Egyptian Clover",
        "برسيم مصري",
        "Trifolium alexandrinum",
        "fodder",
        False,
        200,
        5.0,
        28.0,
        ("ndvi",),
    ),
    (
        "tomato",
        "Tomato",
        "طماطم",
        "Solanum lycopersicum",
        "vegetable",
        False,
        110,
        10.0,
        30.0,
        ("ndvi", "ndre"),
    ),
    (
        "potato",
        "Potato",
        "بطاطس",
        "Solanum tuberosum",
        "vegetable",
        False,
        120,
        7.0,
        25.0,
        ("ndvi",),
    ),
    ("onion", "Onion", "بصل", "Allium cepa", "vegetable", False, 150, 5.0, 25.0, ("ndvi",)),
    ("garlic", "Garlic", "ثوم", "Allium sativum", "vegetable", False, 200, 5.0, 25.0, ("ndvi",)),
    (
        "citrus_orange",
        "Orange",
        "برتقال",
        "Citrus sinensis",
        "fruit_tree",
        True,
        None,
        13.0,
        35.0,
        ("ndvi", "ndre", "ndwi"),
    ),
    (
        "citrus_mandarin",
        "Mandarin",
        "يوسفي",
        "Citrus reticulata",
        "fruit_tree",
        True,
        None,
        13.0,
        35.0,
        ("ndvi", "ndre", "ndwi"),
    ),
    (
        "mango",
        "Mango",
        "مانجو",
        "Mangifera indica",
        "fruit_tree",
        True,
        None,
        18.0,
        35.0,
        ("ndvi", "ndwi"),
    ),
    (
        "olive",
        "Olive",
        "زيتون",
        "Olea europaea",
        "fruit_tree",
        True,
        None,
        9.0,
        30.0,
        ("ndvi", "ndre"),
    ),
    (
        "date_palm",
        "Date Palm",
        "نخيل البلح",
        "Phoenix dactylifera",
        "fruit_tree",
        True,
        None,
        18.0,
        38.0,
        ("ndvi",),
    ),
    (
        "banana",
        "Banana",
        "موز",
        "Musa acuminata",
        "fruit_tree",
        True,
        None,
        14.0,
        35.0,
        ("ndvi", "ndwi"),
    ),
    (
        "grape",
        "Grape",
        "عنب",
        "Vitis vinifera",
        "fruit_tree",
        True,
        None,
        10.0,
        32.0,
        ("ndvi", "ndre"),
    ),
)


def upgrade() -> None:
    insert_sql = (
        "INSERT INTO public.crops "
        "(code, name_en, name_ar, scientific_name, category, is_perennial, "
        " default_growing_season_days, gdd_base_temp_c, gdd_upper_temp_c, "
        " relevant_indices) "
        "VALUES (:code, :name_en, :name_ar, :scientific_name, :category, "
        "        :is_perennial, :growing_days, :gdd_base, :gdd_upper, "
        "        :relevant_indices) "
        "ON CONFLICT (code) DO NOTHING"
    )

    bind = op.get_bind()
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.types import Text

    stmt = text(insert_sql).bindparams(bindparam("relevant_indices", type_=ARRAY(Text)))

    for row in _CROPS:
        (
            code,
            name_en,
            name_ar,
            scientific,
            category,
            is_perennial,
            growing_days,
            gdd_base,
            gdd_upper,
            relevant_indices,
        ) = row
        bind.execute(
            stmt,
            {
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "scientific_name": scientific,
                "category": category,
                "is_perennial": is_perennial,
                "growing_days": growing_days,
                "gdd_base": gdd_base,
                "gdd_upper": gdd_upper,
                "relevant_indices": list(relevant_indices),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.types import Text

    codes = [row[0] for row in _CROPS]
    bind.execute(
        text("DELETE FROM public.crops WHERE code = ANY(:codes)").bindparams(
            bindparam("codes", type_=ARRAY(Text))
        ),
        {"codes": codes},
    )
