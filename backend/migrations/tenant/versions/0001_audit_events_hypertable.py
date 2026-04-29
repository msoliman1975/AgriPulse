"""audit_events hypertable + audit_data_changes table.

Per data_model § 13.2 and § 13.3. Both tables live in the per-tenant
schema; this migration is applied once per tenant by the runner in
scripts/migrate_tenants.py.

Revision ID: 0001
Revises:
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- audit_events --------------------------------------------------
    # No PK: TimescaleDB hypertables cannot have a PK that excludes the time
    # partitioning column. We declare (time, id) as a composite UNIQUE; the
    # pair is sortable and unique enough for replay logic.
    op.create_table(
        "audit_events",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_kind", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("client_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.UniqueConstraint("time", "id", name="uq_audit_events_time_id"),
        sa.CheckConstraint(
            "actor_kind IN ('user','system','integration')",
            name="ck_audit_events_actor_kind",
        ),
    )

    # Convert to TimescaleDB hypertable on `time`.
    op.execute(
        """
        SELECT create_hypertable(
            'audit_events',
            'time',
            chunk_time_interval => INTERVAL '30 days',
            if_not_exists => TRUE
        )
        """
    )
    # Compression policy: compress chunks older than 60 days, segmented by
    # subject_kind for better selectivity on history queries.
    op.execute(
        """
        ALTER TABLE audit_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'subject_kind'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy('audit_events', INTERVAL '60 days', if_not_exists => TRUE)"
    )
    # Retention: 2 years hot, then chunks are dropped (cold archive is
    # exported to S3 by an out-of-band job — not in this migration).
    op.execute(
        "SELECT add_retention_policy('audit_events', INTERVAL '730 days', if_not_exists => TRUE)"
    )

    op.create_index(
        "ix_audit_events_subject",
        "audit_events",
        ["subject_kind", "subject_id", sa.text("time DESC")],
    )
    op.create_index(
        "ix_audit_events_actor",
        "audit_events",
        ["actor_user_id", sa.text("time DESC")],
        postgresql_where=sa.text("actor_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_events_event_type",
        "audit_events",
        ["event_type", sa.text("time DESC")],
    )
    op.create_index(
        "ix_audit_events_farm",
        "audit_events",
        ["farm_id", sa.text("time DESC")],
        postgresql_where=sa.text("farm_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_events_correlation",
        "audit_events",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    # ---- audit_data_changes -------------------------------------------
    op.create_table(
        "audit_data_changes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_schema", sa.Text(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("row_pk", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('INSERT','UPDATE','DELETE')",
            name="ck_audit_data_changes_operation",
        ),
    )
    op.create_index(
        "ix_audit_data_changes_row",
        "audit_data_changes",
        ["table_schema", "table_name", "row_pk", sa.text("changed_at DESC")],
    )
    op.create_index(
        "ix_audit_data_changes_actor",
        "audit_data_changes",
        ["actor_user_id", sa.text("changed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_data_changes_actor", table_name="audit_data_changes")
    op.drop_index("ix_audit_data_changes_row", table_name="audit_data_changes")
    op.drop_table("audit_data_changes")

    op.execute("SELECT remove_retention_policy('audit_events', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('audit_events', if_exists => TRUE)")
    op.drop_index("ix_audit_events_correlation", table_name="audit_events")
    op.drop_index("ix_audit_events_farm", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_subject", table_name="audit_events")
    op.drop_table("audit_events")
