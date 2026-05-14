"""Idempotency index for recommendation-sourced notification dispatches.

Mirrors the existing ``uq_notification_dispatches_alert_chan_user_active``
partial UNIQUE for the recommendation_id source. Without this, the
recommendations fan-out subscriber could re-insert the same (rec,
channel, user) row on a duplicate event delivery (e.g. a still-firing
re-evaluation) instead of silently no-op'ing on the SAVEPOINT-wrapped
INSERT.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_notification_dispatches_rec_chan_user_active",
        "notification_dispatches",
        ["recommendation_id", "channel", "recipient_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'sent') AND recommendation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_notification_dispatches_rec_chan_user_active",
        table_name="notification_dispatches",
    )
