"""Drop the eight `platform_defaults` keys that no runtime code reads.

Audit of the /platform/defaults surface found that 11 of 12 seeded keys
were inert: each had a parallel env-var setting in ``app/core/settings.py``
that the pipeline actually honours, and the ``platform_defaults`` row was
never consulted. Editing them changed a row and an audit entry, nothing
else — and in three cases the two sources disagreed outright.

This drops the eight with no live plumbing at any tier:

  weather.forecast_retention_days   no consumer; no prune job reads it
  imagery.default_product_code      no consumer, and the seeded value
                                    ('sentinel2_l2a') never matched the
                                    catalog code ('s2_l2a')
  email.from_address                smtp.py uses settings.smtp_from
  email.smtp_host                   smtp.py uses settings.smtp_host
  webhook.signing_alg               no consumer
  webhook.timeout_seconds           webhook.py uses 5.0; this said 10
  alert.rate_limit_per_hour         no consumer, not surfaced anywhere
  alert.channel_types_enabled       no consumer, not surfaced anywhere

Four keys stay:

  grid.anomaly_z_threshold          read by app/modules/grid/{snapshot,tasks}.py
  imagery.cloud_cover_threshold_pct block tier (imagery_aoi_subscriptions
                                    .cloud_cover_max_pct) is read by
                                    imagery/tasks.py
  weather.default_provider_code     mirrors settings.* — kept as the
  weather.default_cadence_hours     documented tenant-visible default

``tenant_settings_overrides.key`` is FK'd to ``platform_defaults.key`` ON
DELETE RESTRICT, so the override rows must go first or the DELETE errors.
Any tenant that overrode one of these keys was overriding something inert,
so dropping the override loses no behaviour.

Irreversible in the strict sense: ``downgrade`` restores the key rows with
their original seed values (matching 0020/0026), but tenant override rows
that were deleted on the way up are not resurrected.

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-29
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, value, value_schema, category, description) — values mirror the
# original 0020 seed so `downgrade` is a faithful restore.
DROPPED: list[tuple[str, object, str, str, str]] = [
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
        "SMTP server hostname. Tenant override takes precedence; "
        "null means use the env-config server.",
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

_KEYS = [key for key, *_ in DROPPED]


def upgrade() -> None:
    conn = op.get_bind()
    # FK is ON DELETE RESTRICT — clear dependent overrides first.
    conn.execute(
        text("DELETE FROM public.tenant_settings_overrides WHERE key = ANY(:keys)").bindparams(
            bindparam("keys", type_=postgresql.ARRAY(postgresql.TEXT))
        ),
        {"keys": _KEYS},
    )
    conn.execute(
        text("DELETE FROM public.platform_defaults WHERE key = ANY(:keys)").bindparams(
            bindparam("keys", type_=postgresql.ARRAY(postgresql.TEXT))
        ),
        {"keys": _KEYS},
    )


def downgrade() -> None:
    conn = op.get_bind()
    stmt = text(
        """
        INSERT INTO public.platform_defaults
            (key, value, value_schema, description, category)
        VALUES
            (:key, CAST(:value AS jsonb), :value_schema, :description, :category)
        ON CONFLICT (key) DO NOTHING
        """
    )
    for key, value, schema, category, desc in DROPPED:
        conn.execute(
            stmt,
            {
                "key": key,
                "value": json.dumps(value),
                "value_schema": schema,
                "category": category,
                "description": desc,
            },
        )
