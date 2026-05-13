"""Seed `platform_defaults` with V1 keys.

Idempotent: ON CONFLICT DO NOTHING so re-running on an existing DB
doesn't overwrite operator edits made via the /admin UI. Adding a new
default in a future revision requires a new migration that does the
same.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-08
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, value, value_schema, category, description)
SEEDS: list[tuple[str, object, str, str, str]] = [
    (
        "weather.default_provider_code",
        "open_meteo",
        "string",
        "weather",
        "Default weather data provider for new tenants.",
    ),
    (
        "weather.default_cadence_hours",
        3,
        "number",
        "weather",
        "How often the weather pipeline polls each subscription.",
    ),
    (
        "weather.forecast_retention_days",
        90,
        "number",
        "weather",
        "How long forecast rows are retained before pruning.",
    ),
    (
        "imagery.default_product_code",
        "sentinel2_l2a",
        "string",
        "imagery",
        "Default satellite product code for new imagery subscriptions.",
    ),
    (
        "imagery.cloud_cover_threshold_pct",
        30,
        "number",
        "imagery",
        "Maximum cloud cover (%) accepted by ingestion. Scenes above are skipped.",
    ),
    (
        "email.from_address",
        "noreply@agripulse.com",
        "string",
        "email",
        "From address for outbound transactional email.",
    ),
    (
        "email.smtp_host",
        None,
        "string",
        "email",
        "SMTP server hostname. Tenant override takes precedence; null means use the env-config server.",
    ),
    (
        "webhook.signing_alg",
        "hmac-sha256",
        "string",
        "webhook",
        "Signature algorithm applied to outbound webhook payloads.",
    ),
    (
        "webhook.timeout_seconds",
        10,
        "number",
        "webhook",
        "Request timeout (seconds) for outbound webhook calls.",
    ),
    (
        "alert.rate_limit_per_hour",
        60,
        "number",
        "alert",
        "Maximum number of alerts a tenant may emit per hour before throttling.",
    ),
    (
        "alert.channel_types_enabled",
        ["email", "webhook"],
        "array",
        "alert",
        "Channel types tenants may register instances on. New types require a code change.",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    for key, value, schema, category, desc in SEEDS:
        conn.execute(
            _stmt(),
            {
                "key": key,
                "value": json.dumps(value),
                "value_schema": schema,
                "category": category,
                "description": desc,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key, *_ in SEEDS:
        conn.execute(_delete_stmt(), {"key": key})


def _stmt():
    from sqlalchemy import text

    return text(
        """
        INSERT INTO public.platform_defaults
            (key, value, value_schema, description, category)
        VALUES
            (:key, CAST(:value AS jsonb), :value_schema, :description, :category)
        ON CONFLICT (key) DO NOTHING
        """
    )


def _delete_stmt():
    from sqlalchemy import text

    return text("DELETE FROM public.platform_defaults WHERE key = :key")
