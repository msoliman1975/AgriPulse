"""Weather-indices catalog + seed (Weather-Indices PR-W1).

A new `public` curated catalog — `weather_indices_catalog` — that
promotes weather to a first-class **index family** alongside the
vegetation `indices_catalog`. Mirrors `weather_derived_signals_catalog`
in shape but carries the extra display + agronomy metadata the SPA
picker, tooltips, and the Phase-2 risk authoring need:

  - `unit`, `value_min`/`value_max` (color-ramp bounds; nullable —
    weather is unbounded and the SPA autoscales in V1).
  - `source_kind` (`observed` | `derived`).
  - `default_visible`, `sort_order` (picker ordering / compact subset).
  - `relation_*_en/ar` — the "relationship to other indices / diseases /
    insects" text straight from the agronomists' sheet. The disease /
    insect columns become Phase-2 risk-model knowledge; they live here
    so the UI can show "why this matters" and authoring can reference it.

Seeded with the 7 indices from `weather indices(Sheet1).csv`. Codes
match the `index_code` the PR-W2 projection task writes into
`weather_index_daily`. Re-running is a no-op (`ON CONFLICT DO NOTHING`).

#6 `evaporation_coeff` is **redefined** (vs the sheet's literal
"evaporation factor") as a rolling soil dry-down / water-deficit stock
— see docs/proposals/weather-indices-first-class.md §1. The original
`epan = et0/0.7` proxy was a linear rescale of ET₀ (degenerate) and was
dropped.

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- The 7 weather indices (verbatim EN/AR from the agronomists' sheet) -----
# `code` == the index_code PR-W2 writes into weather_index_daily.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "temperature",
        "name_en": "Max/Min Temperature",
        "name_ar": "مؤشر درجة الحرارة العظمى والصغرى",
        "unit": "°C",
        "source_kind": "observed",
        "sort_order": 1,
        "description_en": "Daily max / min / mean air temperature at the farm centroid.",
        "description_ar": "درجة حرارة الهواء العظمى والصغرى والمتوسطة اليومية عند مركز المزرعة.",
        "relation_indices_en": (
            "High temp increases evapotranspiration; low temp reduces "
            "photosynthesis → linked to Radiation & Evapotranspiration."
        ),
        "relation_indices_ar": (
            "الحرارة العالية تزيد البخر-نتح؛ الحرارة المنخفضة تقلل التمثيل "
            "الضوئي → مرتبطة بالأشعة والنتح."
        ),
        "relation_disease_en": "Heat stress predisposes mango to powdery mildew and sunburn.",
        "relation_disease_ar": "الإجهاد الحراري يزيد احتمالية الإصابة بالبياض الدقيقي وحروق الشمس.",
        "relation_insect_en": (
            "High temp reduces pollinator activity; low temp slows insect metabolism."
        ),
        "relation_insect_ar": "الحرارة العالية تقلل نشاط الملقحات؛ الحرارة المنخفضة تبطئ أيض الحشرات.",
    },
    {
        "code": "radiation",
        "name_en": "Solar Radiation",
        "name_ar": "مؤشر كمية الأشعة",
        "unit": "W/m²",
        "source_kind": "observed",
        "sort_order": 2,
        "description_en": "Shortwave solar radiation; daily mean and total.",
        "description_ar": "الأشعة الشمسية قصيرة الموجة؛ المتوسط والإجمالي اليومي.",
        "relation_indices_en": (
            "High radiation boosts NDVI/PRI; low radiation reduces chlorophyll indices."
        ),
        "relation_indices_ar": (
            "الأشعة العالية تعزز NDVI/PRI؛ الأشعة المنخفضة تقلل مؤشرات الكلوروفيل."
        ),
        "relation_disease_en": "Excess radiation causes leaf scorch; low radiation favors fungal growth.",
        "relation_disease_ar": "الأشعة الزائدة تسبب احتراق الأوراق؛ الأشعة المنخفضة تشجع نمو الفطريات.",
        "relation_insect_en": (
            "High radiation increases insect activity; low radiation reduces pest mobility."
        ),
        "relation_insect_ar": "الأشعة العالية تزيد نشاط الحشرات؛ الأشعة المنخفضة تقلل حركة الآفات.",
    },
    {
        "code": "wind",
        "name_en": "Wind Speed & Direction",
        "name_ar": "مؤشر سرعة واتجاه الرياح",
        "unit": "m/s, °",
        "source_kind": "observed",
        "sort_order": 3,
        "description_en": "Wind speed (mean/max) and vector-mean direction.",
        "description_ar": "سرعة الرياح (المتوسط/الأقصى) والاتجاه المتجهي المتوسط.",
        "relation_indices_en": (
            "Strong wind increases evapotranspiration; wind direction affects "
            "rainfall distribution."
        ),
        "relation_indices_ar": "الرياح القوية تزيد البخر-نتح؛ اتجاه الرياح يؤثر على توزيع المطر.",
        "relation_disease_en": "Wind spreads fungal spores (anthracnose, powdery mildew).",
        "relation_disease_ar": "الرياح تنشر جراثيم الأمراض الفطرية (الأنثراكنوز، البياض الدقيقي).",
        "relation_insect_en": "Wind disperses insect pests (whiteflies, aphids).",
        "relation_insect_ar": "الرياح تنشر الآفات الحشرية (الذباب الأبيض والمنّ).",
    },
    {
        "code": "rainfall",
        "name_en": "Rainfall Amount & Density",
        "name_ar": "مؤشر كمية وكثافة المطر",
        "unit": "mm",
        "source_kind": "observed",
        "sort_order": 4,
        "description_en": "Daily precipitation plus rolling 7-/30-day totals.",
        "description_ar": "هطول الأمطار اليومي بالإضافة إلى الإجماليات المتحركة لـ 7 و30 يومًا.",
        "relation_indices_en": (
            "Rainfall reduces evapotranspiration demand; excess rainfall linked "
            "to disease outbreaks."
        ),
        "relation_indices_ar": "المطر يقلل الحاجة للبخر-نتح؛ الأمطار الزائدة مرتبطة بانتشار الأمراض.",
        "relation_disease_en": "Heavy rain increases anthracnose and root rot.",
        "relation_disease_ar": "الأمطار الغزيرة تزيد الأنثراكنوز وأعفان الجذور.",
        "relation_insect_en": "Rainfall creates humid microclimate favoring fruit flies and gnats.",
        "relation_insect_ar": "المطر يخلق مناخًا رطبًا يشجع ذباب الفاكهة والبعوض الفطري.",
    },
    {
        "code": "evapotranspiration",
        "name_en": "Plant Water Loss (ET₀)",
        "name_ar": "مؤشر نتح النبات للمياه",
        "unit": "mm",
        "source_kind": "observed",
        "sort_order": 5,
        "description_en": "FAO-56 Penman-Monteith reference evapotranspiration (daily total).",
        "description_ar": "البخر-نتح المرجعي حسب FAO-56 بنمان-مونتيث (الإجمالي اليومي).",
        "relation_indices_en": "Directly linked to Temperature, Radiation, Wind, and Rainfall.",
        "relation_indices_ar": "مرتبط مباشرة بالحرارة والأشعة والرياح والمطر.",
        "relation_disease_en": (
            "High evapotranspiration increases drought stress → predisposes to leaf scorch."
        ),
        "relation_disease_ar": "النتح العالي يزيد الإجهاد المائي → يسبب احتراق الأوراق.",
        "relation_insect_en": (
            "High evapotranspiration reduces insect survival; low evapotranspiration "
            "favors pest breeding."
        ),
        "relation_insect_ar": "النتح العالي يقلل بقاء الحشرات؛ النتح المنخفض يشجع تكاثر الآفات.",
    },
    {
        # Redefined: rolling Σ(ET₀ - precip) — soil dry-down / water-deficit
        # STOCK (the running counterpart to the rain_et_balance flux).
        "code": "evaporation_coeff",
        "name_en": "Soil Dry-down / Water Deficit",
        "name_ar": "مؤشر معامل البخر",
        "unit": "mm",
        "source_kind": "derived",
        "sort_order": 6,
        "description_en": (
            "Rolling 30-day sum of (ET₀ - rainfall): cumulative soil water deficit / "
            "dry-down. Proxy for soil dryness that drives wilt and soil-larvae "
            "conditions. V1 stand-in for a full soil-water-balance model."
        ),
        "description_ar": (
            "مجموع متحرك لـ 30 يومًا لـ (البخر-نتح - المطر): العجز المائي التراكمي "
            "للتربة / الجفاف. مؤشر بديل لجفاف التربة المسبب للذبول ويرقات التربة."
        ),
        "relation_indices_en": (
            "Closely related to Evapotranspiration & the Rainfall↔ET Balance "
            "(cumulative dry-down stock vs daily flux)."
        ),
        "relation_indices_ar": "مرتبط ارتباطًا وثيقًا بمؤشر النتح وميزان المطر-النتح (تراكم العجز المائي).",
        "relation_disease_en": "High evaporation dries soil → increases wilt diseases.",
        "relation_disease_ar": "البخر العالي يجفف التربة → يزيد أمراض الذبول.",
        "relation_insect_en": "Dry soil reduces soil-borne insect larvae; moist soil favors them.",
        "relation_insect_ar": "التربة الجافة تقلل يرقات الحشرات الأرضية؛ التربة الرطبة تشجعها.",
    },
    {
        "code": "rain_et_balance",
        "name_en": "Rainfall ↔ ET Balance",
        "name_ar": "مؤشر علاقة المطر والنتح",
        "unit": "mm",
        "source_kind": "derived",
        "sort_order": 7,
        "description_en": (
            "Daily water balance: rainfall - ET₀. Positive = surplus, "
            "negative = deficit (today's flux)."
        ),
        "description_ar": "الميزان المائي اليومي: المطر - البخر-نتح. الموجب فائض والسالب عجز (التدفق اليومي).",
        "relation_indices_en": "Balanced rainfall reduces evapotranspiration stress.",
        "relation_indices_ar": "المطر المتوازن يقلل الإجهاد الناتج عن النتح.",
        "relation_disease_en": (
            "Imbalance (low rain + high evapotranspiration) increases disease risk."
        ),
        "relation_disease_ar": "عدم التوازن (مطر قليل + نتح عالي) يزيد خطر الأمراض.",
        "relation_insect_en": "Imbalance affects pest cycles (drought reduces, humidity increases).",
        "relation_insect_ar": "عدم التوازن يؤثر على دورة الآفات (الجفاف يقللها، الرطوبة تزيدها).",
    },
)

_CODES: tuple[str, ...] = tuple(str(e["code"]) for e in _INDICES)


def upgrade() -> None:
    op.create_table(
        "weather_indices_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        # Color-ramp bounds — nullable; weather is unbounded and the SPA
        # autoscales / uses the climatology band in V1.
        sa.Column("value_min", sa.Numeric(10, 3), nullable=True),
        sa.Column("value_max", sa.Numeric(10, 3), nullable=True),
        sa.Column("source_kind", sa.Text(), nullable=False, server_default=sa.text("'observed'")),
        sa.Column(
            "default_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Agronomy relationship text from the sheet (Phase-2 risk knowledge).
        sa.Column("relation_indices_en", sa.Text(), nullable=True),
        sa.Column("relation_indices_ar", sa.Text(), nullable=True),
        sa.Column("relation_disease_en", sa.Text(), nullable=True),
        sa.Column("relation_disease_ar", sa.Text(), nullable=True),
        sa.Column("relation_insect_en", sa.Text(), nullable=True),
        sa.Column("relation_insect_ar", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # Unnamed UNIQUE → the `uq_%(table)s_%(column_0)s` convention
        # generates `uq_weather_indices_catalog_code`. The CHECK passes a
        # bare suffix — its `ck_%(table)s_%(constraint_name)s` convention
        # prepends the prefix (a full name here would double + truncate it).
        sa.UniqueConstraint("code"),
        sa.CheckConstraint(
            "source_kind IN ('observed','derived')",
            name="source_kind",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_weather_indices_catalog_updated_at "
        "BEFORE UPDATE ON public.weather_indices_catalog "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # Parameterized seed — binds handle the Arabic + arrow glyphs safely.
    insert = sa.text(
        """
        INSERT INTO public.weather_indices_catalog (
            code, name_en, name_ar, unit, description_en, description_ar,
            source_kind, default_visible, sort_order,
            relation_indices_en, relation_indices_ar,
            relation_disease_en, relation_disease_ar,
            relation_insect_en, relation_insect_ar, is_active
        ) VALUES (
            :code, :name_en, :name_ar, :unit, :description_en, :description_ar,
            :source_kind, TRUE, :sort_order,
            :relation_indices_en, :relation_indices_ar,
            :relation_disease_en, :relation_disease_ar,
            :relation_insect_en, :relation_insect_ar, TRUE
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    bind = op.get_bind()
    for entry in _INDICES:
        bind.execute(insert, entry)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_weather_indices_catalog_updated_at "
        "ON public.weather_indices_catalog"
    )
    op.drop_table("weather_indices_catalog")
