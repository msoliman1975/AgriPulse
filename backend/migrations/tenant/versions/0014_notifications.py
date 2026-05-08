"""notification_dispatches + in_app_inbox — tenant-side of notifications.

PR-S4-B of Slice 4. Two tables:

  * `notification_dispatches` — one row per (event × channel × recipient).
    Status lifecycle: ``pending`` → ``sent`` (or ``failed`` / ``skipped``).
    Partial UNIQUE on ``(alert_id, channel, recipient_user_id)`` WHERE
    status IN ('pending','sent') keeps the dispatcher idempotent: a
    rerun won't re-send.
  * `in_app_inbox` — the bell-icon's data source. One row per inbox
    item per user. Read/archive timestamps are mutated; rows are
    soft-deleted (``deleted_at``) rather than hard-removed so audit
    history survives.

Cross-schema FKs to ``public.users`` and ``public.alerts`` are not
enforced (we follow the same pattern as ``alerts.created_by`` etc.).

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- notification_dispatches --------------------------------------
    op.create_table(
        "notification_dispatches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # Source events. Exactly one of (alert_id, recommendation_id)
        # is non-null per row; recommendation_id stays nullable for
        # forward compat (recommendations module is a stub today).
        # Logical reference to alerts.id, not enforced as a DB FK. The
        # cross-module subscriber writes from a separate sync connection
        # while the publishing async transaction is still open, so a DB
        # FK would race the alert insert. Dangling alert_ids are rare
        # (would require a publishing-tx rollback after handler success);
        # consumers tolerate them by reading title/body off the row.
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_code", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        # Recipient: user UUID for in_app/email; null for webhook (the
        # tenant's webhook URL is the addressee, snapshotted here).
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_address", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("rendered_subject", sa.Text(), nullable=True),
        sa.Column("rendered_body", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_notification_dispatches_channel",
        "notification_dispatches",
        "channel IN ('in_app', 'email', 'webhook')",
    )
    op.create_check_constraint(
        "ck_notification_dispatches_status",
        "notification_dispatches",
        "status IN ('pending', 'sent', 'failed', 'skipped')",
    )
    op.create_check_constraint(
        "ck_notification_dispatches_source",
        "notification_dispatches",
        "(alert_id IS NOT NULL)::int + (recommendation_id IS NOT NULL)::int = 1",
    )
    # Idempotency: don't re-dispatch the same channel to the same user
    # for a still-pending or already-sent message.
    op.create_index(
        "uq_notification_dispatches_alert_chan_user_active",
        "notification_dispatches",
        ["alert_id", "channel", "recipient_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'sent') AND alert_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notification_dispatches_status_created",
        "notification_dispatches",
        ["status", sa.text("created_at DESC")],
    )

    # --- in_app_inbox -------------------------------------------------
    op.create_table(
        "in_app_inbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # See note on notification_dispatches.alert_id — same trade-off.
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_in_app_inbox_severity",
        "in_app_inbox",
        "severity IS NULL OR severity IN ('info', 'warning', 'critical')",
    )
    # Hot path: unread items for a user, newest first.
    op.create_index(
        "ix_in_app_inbox_user_unread",
        "in_app_inbox",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("read_at IS NULL AND archived_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_in_app_inbox_user_created",
        "in_app_inbox",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_in_app_inbox_user_created", table_name="in_app_inbox")
    op.drop_index("ix_in_app_inbox_user_unread", table_name="in_app_inbox")
    op.drop_constraint("ck_in_app_inbox_severity", "in_app_inbox", type_="check")
    op.drop_table("in_app_inbox")

    op.drop_index(
        "ix_notification_dispatches_status_created",
        table_name="notification_dispatches",
    )
    op.drop_index(
        "uq_notification_dispatches_alert_chan_user_active",
        table_name="notification_dispatches",
    )
    op.drop_constraint(
        "ck_notification_dispatches_source", "notification_dispatches", type_="check"
    )
    op.drop_constraint(
        "ck_notification_dispatches_status", "notification_dispatches", type_="check"
    )
    op.drop_constraint(
        "ck_notification_dispatches_channel", "notification_dispatches", type_="check"
    )
    op.drop_table("notification_dispatches")
