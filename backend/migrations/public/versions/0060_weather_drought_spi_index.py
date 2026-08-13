"""Seed `drought_spi` into the weather catalog (indices-guide gap audit).

The Standardized Precipitation Index (McKee et al. 1993; WMO-1090), computed
over a 90-day window by ``weather.compute_spi_for_tenant``.

Two things this row records that the guide does not:

**It is not the index the guide describes.** The guide's "Agricultural Drought
Index" combines rainfall, ET₀ and soil moisture — which is PDSI or WRSI, not
SPI, and the guide concedes as much in its own confidence note. SPI is the
precipitation-only index, and it is the one with a WMO standard behind it. What
ships here is the citable one, described honestly, rather than a composite with
no agreed definition.

**It will often be absent in Egypt, on purpose.** SPI degrades where most
windows are completely dry, because the zero point mass dominates the mixed
distribution and the index collapses to a near-binary signal. Nile Valley and
Delta rainfall is on the order of tens of millimetres a year. The task declines
to emit a row in that case rather than publishing a fabricated 0.0, so expect a
sparse or empty series for arid farms — that is the index reporting its own
limits, not a pipeline fault.

`value_min`/`value_max` are set to ±3, matching the clamp the computation
applies: beyond three sigma the fitted tail is extrapolation from a handful of
observations rather than measurement.

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX: dict[str, object] = {
    "code": "drought_spi",
    "name_en": "Drought (SPI-90)",
    "name_ar": "الجفاف (مؤشر الهطول المعياري 90 يومًا)",
    "unit": "sigma",
    "source_kind": "derived",
    "sort_order": 12,
    "value_min": -3,
    "value_max": 3,
    "description_en": (
        "Standardized Precipitation Index over 90 days: how far this farm's rainfall "
        "total sits from its own long-run normal for the time of year, in standard "
        "deviations. Negative is dry, below -1.5 is a meaningful drought, positive is "
        "wetter than usual. Unlike every other weather index this one is already an "
        "anomaly, so it carries no baseline deviation of its own. Absent for farms "
        "whose rainfall record is too short or too consistently dry to fit — an SPI "
        "there would be an artefact rather than a measurement."
    ),
    "description_ar": (
        "مؤشر الهطول المعياري على مدى 90 يومًا: كم يبعد إجمالي مطر هذه المزرعة عن "
        "معدّلها الطويل لهذا الوقت من السنة، بالانحرافات المعيارية. السالب جاف، وما "
        "دون -1.5 جفاف معتبر، والموجب أرطب من المعتاد. وخلافًا لكل مؤشرات الطقس "
        "الأخرى فهذا المؤشر شذوذ في ذاته، فلا يحمل انحرافًا عن خط أساس. ويغيب عن "
        "المزارع التي يكون سجلها المطري أقصر أو أشد جفافًا من أن يُلائَم — فالقيمة "
        "هناك تكون أثرًا حسابيًّا لا قياسًا."
    ),
    "relation_indices_en": (
        "Derived from the rainfall index's own history. Read alongside the "
        "rainfall-to-ET balance: SPI says whether this season is unusual, the balance "
        "says whether today's crop demand was met."
    ),
    "relation_indices_ar": (
        "مشتقّ من تاريخ مؤشر المطر نفسه. يُقرأ مع ميزان المطر والنتح: SPI يقول إن كان "
        "هذا الموسم غير معتاد، والميزان يقول إن كان طلب المحصول اليوم قد لُبّي."
    ),
    "relation_disease_en": (
        "Prolonged drought suppresses foliar fungal disease while raising mite and "
        "scale pressure."
    ),
    "relation_disease_ar": (
        "الجفاف المطوّل يثبّط الأمراض الفطرية الورقية ويرفع ضغط الأكاروسات والحشرات القشرية."
    ),
    "relation_insect_en": "Drought concentrates pests onto irrigated blocks.",
    "relation_insect_ar": "الجفاف يركّز الآفات على القطاعات المرويّة.",
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO public.weather_indices_catalog (
                code, name_en, name_ar, unit, description_en, description_ar,
                source_kind, default_visible, sort_order, value_min, value_max,
                relation_indices_en, relation_indices_ar,
                relation_disease_en, relation_disease_ar,
                relation_insect_en, relation_insect_ar, is_active
            ) VALUES (
                :code, :name_en, :name_ar, :unit, :description_en, :description_ar,
                :source_kind, TRUE, :sort_order, :value_min, :value_max,
                :relation_indices_en, :relation_indices_ar,
                :relation_disease_en, :relation_disease_ar,
                :relation_insect_en, :relation_insect_ar, TRUE
            )
            ON CONFLICT (code) DO NOTHING
            """
        ),
        _INDEX,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM public.weather_indices_catalog WHERE code = 'drought_spi'")
    )
