"""Seed leaf_wetness, frost_risk and heat_stress into the weather catalog.

From the indices-guide gap audit (docs/guide/agri-indices-gap-analysis.html).
All three are computed from hourly readings we already fetch AND store —
temperature and relative humidity — so none needs a provider change, and all
three backfill retroactively over the whole archive via
``weather.backfill_weather_indices``.

  * ``leaf_wetness`` — hours at/above 90% RH (the NHRH90 model). The strongest
    single predictor of fungal infection, and the input the three mango
    pathogen models were built without: they approximate wetness from daily
    mean RH because hourly wetness did not exist when they were written.
  * ``frost_risk``   — 0-100 closeness to frost from the daily minimum. The
    only signal in the platform that fires BEFORE damage rather than after.
  * ``heat_stress``  — Thom's Temperature-Humidity Index.

Appended at sort_order 9-11; existing rows keep their positions, exactly as
0049 did for ``humidity``.

⚠️ Seeding a catalog row makes the observer's weather lane expect that code in
``weather_index_daily``, so the coverage ribbon will show a shortfall until the
projection has run for a farm. That is correct behaviour, not a regression —
it is the ribbon reporting a real gap.

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Parameterised inserts, not f-strings: the Arabic text and the → glyphs do
# not survive string building reliably. Same rule 0037 and 0049 followed.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "leaf_wetness",
        "name_en": "Leaf Wetness Duration",
        "name_ar": "مدة بلل الأوراق",
        "unit": "h",
        "source_kind": "derived",
        "sort_order": 9,
        # 0-24 by construction, so the ramp bounds are real rather than a guess.
        "value_min": 0,
        "value_max": 24,
        "description_en": (
            "Hours in the day at or above 90% relative humidity — the NHRH90 estimate of "
            "how long leaves stayed wet from dew or rain. Fungal spores need free water to "
            "germinate, which makes this the strongest single weather predictor of infection."
        ),
        "description_ar": (
            "عدد ساعات اليوم التي بلغت فيها الرطوبة النسبية 90% فأكثر — تقدير NHRH90 لمدة "
            "بقاء الأوراق مبتلّة من الندى أو المطر. الجراثيم الفطرية تحتاج ماءً حرًّا لتنبت، "
            "وهو ما يجعل هذا أقوى منبّئ مناخي منفرد بالإصابة."
        ),
        "relation_indices_en": (
            "Rises with humidity and rainfall, falls with wind and radiation, which dry the "
            "canopy faster."
        ),
        "relation_indices_ar": (
            "يرتفع مع الرطوبة والمطر، وينخفض مع الرياح والإشعاع اللذين يجففان المجموع "
            "الخضري أسرع."
        ),
        "relation_disease_en": (
            "The core input to infection models. Most foliar pathogens need a sustained wet "
            "period — often more than 6-10 continuous hours — before infection takes."
        ),
        "relation_disease_ar": (
            "المُدخل الأساسي لنماذج الإصابة. معظم مسبّبات الأمراض الورقية تحتاج فترة بلل "
            "متصلة — غالبًا أكثر من 6 إلى 10 ساعات — قبل أن تقع الإصابة."
        ),
        "relation_insect_en": "Prolonged wetness favours fungus gnats and slugs; dry canopies favour mites.",
        "relation_insect_ar": "البلل المطوّل يشجع الذباب الفطري والبزاقات؛ والمجاميع الجافة تشجع الأكاروسات.",
    },
    {
        "code": "frost_risk",
        "name_en": "Frost Risk",
        "name_ar": "خطر الصقيع",
        "unit": "score",
        "source_kind": "derived",
        "sort_order": 10,
        "value_min": 0,
        "value_max": 100,
        "description_en": (
            "How close the night came to frost, scored 0-100 from the daily minimum air "
            "temperature: 100 at or below 0°C, 0 at or above 4°C, linear between. "
            "Deliberately not called a probability — a real one needs dew point and a locally "
            "fitted model, and we have neither. Most useful on forecast days, where it is the "
            "only alert that fires before damage rather than after."
        ),
        "description_ar": (
            "مدى اقتراب الليلة من الصقيع، بدرجة من 0 إلى 100 محسوبة من الحرارة الصغرى "
            "اليومية: 100 عند الصفر أو دونه، و0 عند 4 درجات أو فوقها، وخطيًّا بينهما. "
            "ولا يُسمّى احتمالًا عن قصد — فالاحتمال الحقيقي يحتاج نقطة الندى ونموذجًا "
            "محليًّا، وكلاهما غير متوفر. أنفع ما يكون في أيام التوقعات، حيث يكون التنبيه "
            "الوحيد الذي ينطلق قبل وقوع الضرر."
        ),
        "relation_indices_en": (
            "Read against the temperature index it derives from; clear, calm nights (low wind, "
            "low humidity) cool fastest by radiation."
        ),
        "relation_indices_ar": (
            "يُقرأ مقابل مؤشر الحرارة المشتقّ منه؛ والليالي الصافية الساكنة (رياح ورطوبة "
            "منخفضة) تبرد أسرع بالإشعاع."
        ),
        "relation_disease_en": "Frost injury opens wounds that bacterial and fungal pathogens colonise.",
        "relation_disease_ar": "أضرار الصقيع تفتح جروحًا تستوطنها مسبّبات الأمراض البكتيرية والفطرية.",
        "relation_insect_en": "Hard frost suppresses overwintering insect populations.",
        "relation_insect_ar": "الصقيع الشديد يقلل أعداد الحشرات التي تقضي الشتاء.",
    },
    {
        "code": "heat_stress",
        "name_en": "Heat Stress (THI)",
        "name_ar": "الإجهاد الحراري (THI)",
        "unit": "THI",
        "source_kind": "derived",
        "sort_order": 11,
        # Left unbounded: THI is on a Fahrenheit-derived scale with no fixed
        # agricultural range, so the SPA autoscales rather than pinning axes
        # to a band borrowed from livestock science.
        "description_en": (
            "Thom's Temperature-Humidity Index, computed from the day's maximum temperature "
            "and mean relative humidity. Driven by the maximum because heat stress is a "
            "daytime extreme — a day peaking at 40°C is not made safe by a cool night. "
            "⚠️ THI originates in livestock science; its direct crop validity is weaker than a "
            "crop-specific critical-temperature-at-flowering model, which needs per-block "
            "phenology and so cannot live in a farm-wide index. Read it as a comparative "
            "signal, not an absolute verdict."
        ),
        "description_ar": (
            "دليل الحرارة والرطوبة لثوم، محسوبًا من الحرارة العظمى اليومية ومتوسط الرطوبة "
            "النسبية. يعتمد على العظمى لأن الإجهاد الحراري ظاهرة نهارية متطرفة — واليوم "
            "الذي يبلغ ذروته 40 درجة لا تجعله ليلة باردة آمنًا. ⚠️ أصل THI في علوم الإنتاج "
            "الحيواني، وصلاحيته المباشرة للمحاصيل أضعف من نموذج الحرارة الحرجة عند التزهير "
            "الخاص بكل محصول، وهو نموذج يحتاج أطوارًا فينولوجية لكل قطاع فلا يصلح لمؤشر "
            "على مستوى المزرعة. اقرأه كإشارة للمقارنة لا كحكم مطلق."
        ),
        "relation_indices_en": (
            "Combines the temperature and humidity indices; high radiation and low wind push "
            "canopy temperature above air temperature, making the same THI worse."
        ),
        "relation_indices_ar": (
            "يجمع مؤشرَي الحرارة والرطوبة؛ والإشعاع العالي والرياح الضعيفة يرفعان حرارة "
            "المجموع الخضري فوق حرارة الهواء، مما يجعل القيمة نفسها أسوأ."
        ),
        "relation_disease_en": "Heat-stressed trees are more susceptible to powdery mildew and sunburn.",
        "relation_disease_ar": "الأشجار المجهدة حراريًّا أكثر عرضة للبياض الدقيقي وحروق الشمس.",
        "relation_insect_en": "Sustained heat accelerates mite and scale reproduction while suppressing pollinators.",
        "relation_insect_ar": "الحرارة المستمرة تسرّع تكاثر الأكاروسات والحشرات القشرية وتثبّط الملقحات.",
    },
)

_CODES: tuple[str, ...] = tuple(str(e["code"]) for e in _INDICES)


def upgrade() -> None:
    insert = sa.text(
        """
        INSERT INTO public.weather_indices_catalog (
            code, name_en, name_ar, unit, description_en, description_ar,
            source_kind, default_visible, sort_order,
            value_min, value_max,
            relation_indices_en, relation_indices_ar,
            relation_disease_en, relation_disease_ar,
            relation_insect_en, relation_insect_ar, is_active
        ) VALUES (
            :code, :name_en, :name_ar, :unit, :description_en, :description_ar,
            :source_kind, TRUE, :sort_order,
            :value_min, :value_max,
            :relation_indices_en, :relation_indices_ar,
            :relation_disease_en, :relation_disease_ar,
            :relation_insect_en, :relation_insect_ar, TRUE
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    bind = op.get_bind()
    for entry in _INDICES:
        # heat_stress deliberately carries no ramp bounds; fill the binds so
        # every row uses the same statement.
        params = {"value_min": None, "value_max": None, **entry}
        bind.execute(insert, params)


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM public.weather_indices_catalog WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", type_=postgresql.ARRAY(sa.Text()))
        ),
        {"codes": list(_CODES)},
    )
