"""Tenant lifecycle: suspend/restore + grace-window delete + audit archive.

PR-A of the admin-portal rollout. Adds the columns and audit table the
suspend/reactivate/request_delete/purge service methods need:

  * `tenants.suspended_at` — when the tenant entered status='suspended'
  * `tenants.last_status_reason` — operator-supplied reason text
  * `status` CHECK extended to include `pending_delete`
  * `public.audit_events_archive` — outlives the per-tenant
    `audit_events` hypertable, which is dropped with the schema

`deleted_at` (TimestampedMixin) doubles as the start-of-grace-window
timestamp once status flips to `pending_delete`. The partial unique
index on `slug` already excludes deleted_at IS NOT NULL rows, so a
slug becomes free for reuse the moment a tenant is marked for delete.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenants",
        sa.Column("last_status_reason", sa.Text(), nullable=True),
        schema="public",
    )

    op.drop_constraint("ck_tenants_status", "tenants", schema="public", type_="check")
    op.create_check_constraint(
        "ck_tenants_status",
        "tenants",
        "status IN ('active','suspended','pending_delete','archived')",
        schema="public",
    )

    op.create_table(
        "audit_events_archive",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False, server_default=sa.text("'user'")),
        sa.Column("subject_kind", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="public",
    )
    op.create_index(
        "ix_audit_events_archive_subject",
        "audit_events_archive",
        ["subject_kind", "subject_id"],
        schema="public",
    )
    op.create_index(
        "ix_audit_events_archive_occurred_at",
        "audit_events_archive",
        [sa.text("occurred_at DESC")],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_events_archive_occurred_at",
        table_name="audit_events_archive",
        schema="public",
    )
    op.drop_index(
        "ix_audit_events_archive_subject",
        table_name="audit_events_archive",
        schema="public",
    )
    op.drop_table("audit_events_archive", schema="public")

    op.drop_constraint("ck_tenants_status", "tenants", schema="public", type_="check")
    op.create_check_constraint(
        "ck_tenants_status",
        "tenants",
        "status IN ('active','suspended','archived')",
        schema="public",
    )
    op.drop_column("tenants", "last_status_reason", schema="public")
    op.drop_column("tenants", "suspended_at", schema="public")
