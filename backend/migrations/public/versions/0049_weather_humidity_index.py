"""Seed `humidity` as the 8th weather index (weather_indices_catalog).

Relative humidity was already ingested (Open-Meteo `relative_humidity_2m`),
stored per-hour on `weather_observations` / `weather_forecasts`, and
aggregated to a daily mean by `aggregate_radiation_wind_day()` — but it
was consumed *only* internally by the risk models (powdery mildew,
fruit-fly). It had no catalog row, so the projection task never wrote a
`weather_index_daily` row for it and the SPA had nothing to chart: no
trend, no climatology band, no z-score, and no entry in the decision-tree
`weather_index` picker.

This adds the catalog row; the matching `project_indices()` emission
turns the already-computed `humidity_mean_pct` into a first-class daily
index. `sort_order` = 8 (appended, so the existing 7 keep their
positions). Re-running is a no-op (`ON CONFLICT DO NOTHING`).

Note: existing farms only grow a humidity series from the next
projection forward. History needs `backfill_weather_indices`, and — per
the CAGG rolling-refresh limitation — a manual
`refresh_continuous_aggregate` for dates below the watermark.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Same column set / EN+AR shape as the 0037 seed rows.
_HUMIDITY: dict[str, object] = {
    "code": "humidity",
    "name_en": "Relative Humidity",
    "name_ar": "مؤشر الرطوبة النسبية",
    "unit": "%",
    "source_kind": "observed",
    "sort_order": 8,
    "description_en": "Daily mean relative humidity at the farm centroid.",
    "description_ar": "متوسط الرطوبة النسبية اليومية عند مركز المزرعة.",
    "relation_indices_en": (
        "High humidity suppresses evapotranspiration demand; low humidity "
        "raises it → linked to Evapotranspiration & the Rainfall ↔ ET balance."
    ),
    "relation_indices_ar": (
        "الرطوبة العالية تقلل الحاجة للبخر-نتح؛ الرطوبة المنخفضة تزيدها → "
        "مرتبطة بالنتح وميزان المطر والنتح."
    ),
    "relation_disease_en": (
        "Sustained high humidity drives fungal infection (powdery mildew, "
        "anthracnose); prolonged leaf wetness is the main trigger."
    ),
    "relation_disease_ar": (
        "الرطوبة العالية المستمرة تدفع الإصابات الفطرية (البياض الدقيقي، "
        "الأنثراكنوز)؛ وبلل الأوراق لفترات طويلة هو المحفز الرئيسي."
    ),
    "relation_insect_en": (
        "High humidity favors mites and fruit-fly egg survival; very low "
        "humidity suppresses both."
    ),
    "relation_insect_ar": (
        "الرطوبة العالية تشجع الأكاروسات وبقاء بيض ذبابة الفاكهة؛ والرطوبة المنخفضة جدًا تثبطهما."
    ),
}


def upgrade() -> None:
    # Parameterized — binds handle the Arabic + arrow glyphs safely.
    op.get_bind().execute(
        sa.text(
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
        ),
        _HUMIDITY,
    )


def downgrade() -> None:
    # Catalog row only — the tenant-side weather_index_daily / baseline rows
    # keyed 'humidity' are data, not schema, and are left alone (they become
    # inert without a catalog row, exactly as they were before this revision).
    op.get_bind().execute(
        sa.text("DELETE FROM public.weather_indices_catalog WHERE code = :code"),
        {"code": "humidity"},
    )
