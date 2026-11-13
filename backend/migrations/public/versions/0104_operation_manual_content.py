"""Operation manual content fields (Agri Operation PR 1).

Adds to ``plan_template_activities``:

* ``code``: stable per template (random ``act-<hex>`` default for writers
  that name none), so saved plans and plan activities can
  refer to a manual activity across platform edits (decision B3). Backfilled
  as ``<activity_type>-<n>``, numbered by ``sort_order`` within each type.
* ``title`` / ``title_ar`` (E1) and ``notes_ar`` / ``product_name_ar`` /
  ``dosage_ar`` (E3).
* ``evidence_tier`` (E2): ``eg_fao`` (FAO Egypt figures), ``eg`` (Egyptian
  field data), ``generic`` (not Egypt-calibrated) or ``manual`` (taken from a
  published crop manual, e.g. the Organic Medjool Manual). Backfilled from the
  first ``[EG-FAO]`` / ``[EG]`` / ``[GENERIC...]`` tag in the notes.
* ``source_tree_code`` (E2, F1): the decision tree an activity comes from.

Adds to ``plan_templates``: ``revision`` (bumped on each publish) and
``published_at`` (B4, H6).

Backfills titles (English and Arabic) for the live seeded manuals: the six
mango cultivars (0040), the three potato seasons (0041) and the two organic
Medjool manuals (0099; Arabic follows the manual's own terms, 0100). Notes,
products and dosages are not rewritten. Additive only.

See docs/proposals/agri-operation-build-plan.md section 3.1.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104"
down_revision: str | Sequence[str] | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# sort_order -> (title, title_ar)
MANGO: dict[int, tuple[str, str]] = {
    1: ("Post-harvest land prep", "تجهيز الأرض بعد الحصاد"),
    2: ("Post-harvest nitrogen flush (urea)", "دفعة نيتروجين بعد الحصاد (يوريا)"),
    3: ("Micronutrient spray (zinc, iron, boron)", "رش العناصر الصغرى (زنك، حديد، بورون)"),
    4: ("Post-harvest pruning", "تقليم ما بعد الحصاد"),
    5: ("PBZ treatment for flowering induction", "معاملة الباكلوبوترازول لتحفيز التزهير"),
    6: ("Irrigation cut-back for flowering induction", "تقليل الري لتحفيز التزهير"),
    7: ("Protective spray against powdery mildew", "رش وقائي ضد البياض الدقيقي"),
    8: (
        "Pre-bloom fertilizing (phosphorus and potassium)",
        "تسميد ما قبل التزهير (فوسفور وبوتاسيوم)",
    ),
    9: ("Spray against mango leafhopper", "رش ضد نطاط أوراق المانجو"),
    10: ("Scout fruit set and mealybug", "استكشاف عقد الثمار والبق الدقيقي"),
    11: ("Fruit thinning", "خف الثمار"),
    12: ("Regular irrigation through fruit sizing", "ري منتظم أثناء تضخم الثمار"),
    13: ("Fruit-development fertigation (NPK)", "التسميد مع الري أثناء نمو الثمار (NPK)"),
    14: ("Spray for fruit fly and anthracnose", "رش ضد ذبابة الفاكهة والأنثراكنوز"),
    15: ("Harvest at physiological maturity", "الحصاد عند النضج الفسيولوجي"),
    16: ("Post-harvest recovery fertilizing", "تسميد الاستشفاء بعد الحصاد"),
}

# Mango activities that a decision tree also covers (F1). Kept to the links
# the Agri Operation design names; others stay unlinked.
MANGO_TREES: dict[int, str] = {
    5: "t_flower_induction_readiness",
    6: "t_flower_induction_readiness",
    14: "t_anthracnose_mealybug_watch",
    15: "t_fruit_fly_harvest_readiness",
}

POTATO: dict[int, tuple[str, str]] = {
    1: (
        "Land prep, ridging and base phosphorus and potassium",
        "تجهيز الأرض والتخطيط والتسميد الأساسي بالفوسفور والبوتاسيوم",
    ),
    2: ("Planting", "الزراعة"),
    3: ("First nitrogen dose after emergence", "الدفعة الأولى من النيتروجين بعد الإنبات"),
    4: (
        "Spray against aphids, whitefly and tuber moth",
        "رش ضد المن والذبابة البيضاء وفراشة درنات البطاطس",
    ),
    5: ("Regular irrigation", "ري منتظم"),
    6: ("Second nitrogen dose", "الدفعة الثانية من النيتروجين"),
    7: ("Earthing-up", "الترديم"),
    8: ("Preventive spray against late and early blight", "رش وقائي ضد اللفحة المتأخرة والمبكرة"),
    9: (
        "Final nitrogen and potassium for bulking",
        "الدفعة الأخيرة من النيتروجين والبوتاسيوم لتضخم الدرنات",
    ),
    10: (
        "Scout late blight, tuber moth and tuber set",
        "استكشاف اللفحة المتأخرة وفراشة الدرنات وعقد الدرنات",
    ),
    11: ("Haulm-kill before harvest", "التخلص من العرش قبل الحصاد"),
    12: ("Harvest at skin set", "الحصاد بعد تماسك القشرة"),
}

MEDJOOL_BEARING: dict[int, tuple[str, str]] = {
    1: ("Winter irrigation regime", "نظام الري الشتوي"),
    2: ("Winter irrigation regime (end of season)", "نظام الري الشتوي (نهاية الموسم)"),
    3: ("Red palm weevil trap servicing", "خدمة مصائد سوسة النخيل الحمراء"),
    4: ("Red palm weevil inspection", "فحص النخيل لسوسة النخيل الحمراء"),
    5: ("Organic fertilisation of bearing palms", "التسميد العضوي للنخيل المثمر"),
    6: ("Prepare planting holes for spring planting", "تجهيز جور الزراعة الربيعية"),
    7: ("Dethorning and dead frond removal", "إزالة الشوك والسعف الجاف"),
    8: ("Collect and store pollen", "جمع حبوب اللقاح وتخزينها"),
    9: ("Inspect female palms for spathe cracking", "فحص النخيل المؤنث لانشقاق الطلع"),
    10: ("Pollinate opened spathes", "تلقيح الطلع المتفتح"),
    11: ("Bag pollinated inflorescences against cold", "تكييس النورات الملقحة للحماية من البرد"),
    12: ("Bt dust against lesser date moth", "تعفير Bt ضد دودة البلح الصغرى"),
    13: ("Irrigation at flowering and fruit set", "الري أثناء التزهير والعقد"),
    14: ("Irrigation for this season's new plantings", "ري الزراعات الجديدة لهذا الموسم"),
    15: ("Offshoot removal and spring planting", "فصل الفسائل والزراعة الربيعية"),
    16: ("Bt spray against lesser date moth", "رش Bt ضد دودة البلح الصغرى"),
    17: ("Hand thinning of strands and fruits", "الخف اليدوي للشماريخ والثمار"),
    18: ("Adjust bunch number to leaf area", "ضبط عدد العذوق حسب المساحة الورقية"),
    19: ("Kimri irrigation", "الري في مرحلة الكمري"),
    20: ("Bunch bending", "تدلية العذوق"),
    21: ("Foliar potassium, spray 1 of 3", "رش البوتاسيوم على الأوراق، الرشة 1 من 3"),
    22: ("Foliar potassium, spray 2 of 3", "رش البوتاسيوم على الأوراق، الرشة 2 من 3"),
    23: ("Foliar potassium, spray 3 of 3", "رش البوتاسيوم على الأوراق، الرشة 3 من 3"),
    24: ("Dust mite scouting", "استكشاف حلم الغبار"),
    25: ("Summer irrigation regime", "نظام الري الصيفي"),
    26: ("Bag bunches at Khalal", "تكييس العذوق في مرحلة الخلال"),
    27: ("Monitor ripening inside the bags", "متابعة النضج داخل الأكياس"),
    28: ("Prepare planting holes for autumn planting", "تجهيز جور الزراعة الخريفية"),
    29: ("Harvest in passes", "الجني على دفعات"),
    30: ("Autumn irrigation after harvest", "الري الخريفي بعد الحصاد"),
    31: ("Autumn planting window", "موعد الزراعة الخريفية"),
}

MEDJOOL_NEW: dict[int, tuple[str, str]] = {
    1: ("Dig and prepare planting holes", "حفر جور الزراعة وتجهيزها"),
    2: ("Irrigate the holes before planting", "ري الجور قبل الزراعة"),
    3: ("Harden tissue-culture plants", "أقلمة نباتات زراعة الأنسجة"),
    4: ("Prepare nursery-rooted offshoots", "تجهيز الفسائل المجذرة في المشتل"),
    5: ("Planting", "الزراعة"),
    6: ("First irrigation at planting", "الرية الأولى عند الزراعة"),
    7: (
        "Fit protection against sun, wind and animals",
        "تركيب الحماية من الشمس والرياح والحيوانات",
    ),
    8: ("Mulch the basin", "فرش القش في الحوض"),
    9: (
        "Red palm weevil inspection and trap servicing",
        "فحص سوسة النخيل الحمراء وخدمة المصائد",
    ),
    10: ("Light, frequent irrigation", "ري خفيف ومتكرر"),
    11: ("Inspect every new plant", "فحص كل نبتة جديدة"),
    12: ("Record plants with new growth", "تسجيل النباتات التي ظهر عليها نمو جديد"),
    13: ("Irrigation by soil type, first year", "الري حسب نوع التربة في السنة الأولى"),
    14: ("Keep protection on through the first year", "إبقاء الحماية خلال السنة الأولى"),
    15: ("Irrigation in years 2-3", "الري في السنتين الثانية والثالثة"),
    16: (
        "Organic fertilisation, weeding and mulching",
        "التسميد العضوي وإزالة الحشائش والتغطية",
    ),
    17: ("Watch for juvenile-phase abortion", "متابعة إجهاض النورات في الطور اليافع"),
    18: ("Move to the bearing-palm irrigation regime", "الانتقال إلى نظام ري النخيل المثمر"),
    19: ("Watch for the onset of fruiting", "متابعة بداية الإثمار"),
    20: ("Remove ready offshoots", "فصل الفسائل الجاهزة"),
}

_MANGO_CODES = (
    "mango-keitt-eg",
    "mango-zebda-eg",
    "mango-sukkary-eg",
    "mango-alphonso-eg",
    "mango-yasmina-eg",
    "mango-crimson-eg",
)
_POTATO_CODES = ("potato-winter-eg", "potato-summer-eg", "potato-nili-eg")

# template code -> (titles, trees, manual-sourced)
_BACKFILL: dict[str, tuple[dict[int, tuple[str, str]], dict[int, str], bool]] = {
    **{c: (MANGO, MANGO_TREES, False) for c in _MANGO_CODES},
    **{c: (POTATO, {}, False) for c in _POTATO_CODES},
    "medjool-organic-bearing-eg": (MEDJOOL_BEARING, {}, True),
    "medjool-organic-new-planting-eg": (MEDJOOL_NEW, {}, True),
}

_CODE_DEFAULT = "'act-' || replace(gen_random_uuid()::text, '-', '')"

_TAG = re.compile(r"\[(EG-FAO|EG|GENERIC)[^\]]*\]")
_TIER = {"EG-FAO": "eg_fao", "EG": "eg", "GENERIC": "generic"}


def tier_from_notes(notes: str | None) -> str | None:
    """The first evidence tag in a note, as an ``evidence_tier`` value."""
    if not notes:
        return None
    m = _TAG.search(notes)
    return _TIER[m.group(1)] if m else None


def upgrade() -> None:
    op.add_column("plan_template_activities", sa.Column("code", sa.Text()), schema="public")
    for col in ("title", "title_ar", "notes_ar", "product_name_ar", "dosage_ar"):
        op.add_column("plan_template_activities", sa.Column(col, sa.Text()), schema="public")
    op.add_column(
        "plan_template_activities", sa.Column("evidence_tier", sa.Text()), schema="public"
    )
    op.add_column(
        "plan_template_activities", sa.Column("source_tree_code", sa.Text()), schema="public"
    )
    op.add_column(
        "plan_templates",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="public",
    )
    op.add_column(
        "plan_templates",
        sa.Column("published_at", sa.DateTime(timezone=True)),
        schema="public",
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE public.plan_template_activities a
            SET code = n.activity_type || '-' || n.rn
            FROM (
                SELECT id, activity_type,
                       row_number() OVER (
                           PARTITION BY template_id, activity_type ORDER BY sort_order, id
                       ) AS rn
                FROM public.plan_template_activities
            ) n
            WHERE n.id = a.id
            """
        )
    )
    # Writers that don't name a code (raw SQL, older seeds) still get a unique
    # one; the API always sends or assigns a readable ``<type>-<n>`` code.
    op.alter_column(
        "plan_template_activities",
        "code",
        nullable=False,
        server_default=sa.text(_CODE_DEFAULT),
        schema="public",
    )
    op.create_unique_constraint(
        "uq_plan_template_activity_code",
        "plan_template_activities",
        ["template_id", "code"],
        schema="public",
    )
    op.create_check_constraint(
        "ck_plan_template_activity_evidence_tier",
        "plan_template_activities",
        "evidence_tier IS NULL OR evidence_tier IN ('eg_fao', 'eg', 'generic', 'manual')",
        schema="public",
    )
    conn.execute(
        sa.text(
            "UPDATE public.plan_templates SET revision = 1, published_at = updated_at "
            "WHERE status = 'published'"
        )
    )

    # Evidence tier from the notes' tags, for every template.
    rows = conn.execute(
        sa.text("SELECT id, notes FROM public.plan_template_activities WHERE notes IS NOT NULL")
    ).all()
    for row in rows:
        tier = tier_from_notes(row.notes)
        if tier is not None:
            conn.execute(
                sa.text(
                    "UPDATE public.plan_template_activities SET evidence_tier = :t WHERE id = :id"
                ),
                {"t": tier, "id": row.id},
            )

    # Titles, trees and manual-sourced tiers for the seeded manuals.
    for code, (titles, trees, manual) in _BACKFILL.items():
        for sort_order, (title, title_ar) in titles.items():
            conn.execute(
                sa.text(
                    """
                    UPDATE public.plan_template_activities a
                    SET title = :title, title_ar = :title_ar,
                        source_tree_code = COALESCE(:tree, a.source_tree_code),
                        evidence_tier = CASE WHEN :manual THEN 'manual' ELSE a.evidence_tier END
                    FROM public.plan_templates t
                    WHERE t.id = a.template_id AND t.code = :code
                      AND t.deleted_at IS NULL AND a.sort_order = :sort
                    """
                ),
                {
                    "title": title,
                    "title_ar": title_ar,
                    "tree": trees.get(sort_order),
                    "manual": manual,
                    "code": code,
                    "sort": sort_order,
                },
            )


def downgrade() -> None:
    op.drop_constraint(
        "ck_plan_template_activity_evidence_tier",
        "plan_template_activities",
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        "uq_plan_template_activity_code",
        "plan_template_activities",
        type_="unique",
        schema="public",
    )
    for col in (
        "source_tree_code",
        "evidence_tier",
        "dosage_ar",
        "product_name_ar",
        "notes_ar",
        "title_ar",
        "title",
        "code",
    ):
        op.drop_column("plan_template_activities", col, schema="public")
    op.drop_column("plan_templates", "published_at", schema="public")
    op.drop_column("plan_templates", "revision", schema="public")
