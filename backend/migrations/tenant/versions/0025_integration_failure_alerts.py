"""Per-tenant dedup table for integration-failure streak alerts.

PR-IH11.

The streak-watcher beat task fires an in-app inbox notification when a
subscription crosses the consecutive-failure threshold. Without
dedup, every beat cycle would re-fire while the streak persists.

Dedup key is (subscription_id, streak_started_at). When the streak
resets (a success arrives), the *next* streak gets a different
`streak_started_at` and is therefore a new alert.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_failure_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # 'weather' | 'imagery'
        sa.Column("provider_code", sa.Text(), nullable=True),
        sa.Column("streak_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("streak_length_at_alert", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "streak_started_at",
            name="uq_integration_failure_alerts_subscription_streak",
        ),
        sa.CheckConstraint(
            "kind IN ('weather', 'imagery')",
            name="ck_integration_failure_alerts_kind_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("integration_failure_alerts")
