"""provider_probe_results — periodic liveness checks per upstream provider.

The probe task (added in PR-IH5) pings every configured weather +
imagery provider every few minutes and writes a row here. Providers
are global (one Sentinel Hub catalog, one Open-Meteo endpoint), so the
table lives in `public`, not per-tenant schema. Tenant-scoped reads
project this table to only the providers a given tenant has active
subscriptions on.

`quota_used_pct` is reserved for the V2 quota-tracking follow-up
referenced in the proposal — nullable so adding the field later does
not require a migration.

Retention: 7 days; pruning is the probe task's responsibility.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_probe_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("provider_kind", sa.Text(), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column(
            "probe_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("quota_used_pct", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "provider_kind IN ('weather', 'imagery')",
            name="ck_provider_probe_results_kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'timeout')",
            name="ck_provider_probe_results_status_valid",
        ),
        sa.CheckConstraint(
            "quota_used_pct IS NULL OR (quota_used_pct >= 0 AND quota_used_pct <= 100)",
            name="ck_provider_probe_results_quota_range",
        ),
        schema="public",
    )
    op.create_index(
        "ix_provider_probe_results_provider_probe_at",
        "provider_probe_results",
        ["provider_kind", "provider_code", sa.text("probe_at DESC")],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_probe_results_provider_probe_at",
        table_name="provider_probe_results",
        schema="public",
    )
    op.drop_table("provider_probe_results", schema="public")
