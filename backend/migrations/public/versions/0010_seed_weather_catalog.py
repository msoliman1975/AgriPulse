"""Seed the open_meteo provider and the six derived weather signals.

Per data_model § 8 and the locked Slice-4 decisions:

  - Provider: `open_meteo` (kind=`open_api`). Open-Meteo's free tier
    serves all the inputs Penman-Monteith ET₀ needs (radiation, humidity,
    wind), so it's the MVP source.

  - Derived signals: the six rows from data_model § 8.4 — two GDD bases,
    a season-cumulative GDD, daily ET₀, and 7-/30-day cumulative rainfall.
    The formulas live in code (PR-C); this catalog is the i18n + units +
    display surface the dashboard reads.

Re-running the migration is a no-op — every catalog row uses
`ON CONFLICT (code) DO NOTHING`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-05
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- Open-Meteo provider config --------------------------------------------
# Documents what an `weather_providers.config` JSONB blob is expected to
# contain. The free Open-Meteo endpoints don't require auth, so the config
# only carries the base URLs the adapter (PR-B) reads. We don't validate
# inbound bodies against this schema in MVP.
_OPEN_METEO_CONFIG_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["forecast_url", "archive_url"],
    "properties": {
        "forecast_url": {"type": "string", "format": "uri"},
        "archive_url": {"type": "string", "format": "uri"},
    },
    "additionalProperties": False,
}


# ---- Six derived signals ---------------------------------------------------
# `code` matches the column name in `weather_derived_daily` (PR-A) so the
# nightly derivation job (PR-C) can drive computations from this catalog.
_DERIVED_SIGNALS: tuple[dict[str, object], ...] = (
    {
        "code": "gdd_base10",
        "name_en": "Growing Degree Days (base 10°C)",
        "name_ar": "أيام الدرجات النامية (أساس 10°م)",
        "unit": "°C·day",
        "description": (
            "Daily growing degree days, base 10°C. " "max(0, ((Tmax + Tmin) / 2) - 10)."
        ),
    },
    {
        "code": "gdd_base15",
        "name_en": "Growing Degree Days (base 15°C)",
        "name_ar": "أيام الدرجات النامية (أساس 15°م)",
        "unit": "°C·day",
        "description": (
            "Daily growing degree days, base 15°C — for warm-season " "crops (e.g., cotton, maize)."
        ),
    },
    {
        "code": "gdd_cumulative_base10_season",
        "name_en": "Season-cumulative GDD (base 10°C)",
        "name_ar": "تراكم أيام الدرجات النامية للموسم (أساس 10°م)",
        "unit": "°C·day",
        "description": (
            "Running sum of daily GDD base-10 since the season start "
            "marker. Reset by a per-block season event."
        ),
    },
    {
        "code": "et0_mm_daily",
        "name_en": "Reference Evapotranspiration (daily)",
        "name_ar": "البخر-نتح المرجعي (يومي)",
        "unit": "mm",
        "description": (
            "FAO-56 Penman-Monteith reference ET for short grass. "
            "Inputs: solar radiation, air temp, humidity, wind speed."
        ),
    },
    {
        "code": "precip_mm_7d",
        "name_en": "Cumulative rainfall (7 days)",
        "name_ar": "إجمالي الأمطار (7 أيام)",
        "unit": "mm",
        "description": "Rolling 7-day sum of observed precipitation.",
    },
    {
        "code": "precip_mm_30d",
        "name_en": "Cumulative rainfall (30 days)",
        "name_ar": "إجمالي الأمطار (30 يوم)",
        "unit": "mm",
        "description": "Rolling 30-day sum of observed precipitation.",
    },
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO public.weather_providers (code, name, kind, config_schema)
        VALUES (
            'open_meteo',
            'Open-Meteo',
            'open_api',
            '{json.dumps(_OPEN_METEO_CONFIG_SCHEMA)}'::jsonb
        )
        ON CONFLICT (code) DO NOTHING
        """
    )

    for entry in _DERIVED_SIGNALS:
        op.execute(
            f"""
            INSERT INTO public.weather_derived_signals_catalog (
                code, name_en, name_ar, unit, description, is_active
            )
            VALUES (
                '{entry["code"]}',
                $tag${entry["name_en"]}$tag$,
                $tag${entry["name_ar"]}$tag$,
                $tag${entry["unit"]}$tag$,
                $tag${entry["description"]}$tag$,
                TRUE
            )
            ON CONFLICT (code) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.weather_derived_signals_catalog WHERE code IN "
        "('gdd_base10','gdd_base15','gdd_cumulative_base10_season',"
        "'et0_mm_daily','precip_mm_7d','precip_mm_30d')"
    )
    op.execute("DELETE FROM public.weather_providers WHERE code = 'open_meteo'")
