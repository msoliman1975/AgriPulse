"""signal_definitions + signal_assignments + signal_observations.

Per data_model § 9. Custom user-defined data streams. MVP shape:
manual entry only (P2 will add an IoT-ready ingest path).

Three tables, all in the per-tenant schema:

  * `signal_definitions` — what kinds of signals exist for this tenant.
  * `signal_assignments` — which farms/blocks each definition applies to.
    A row with `(farm_id, block_id)` both NULL is tenant-wide.
  * `signal_observations` — TimescaleDB hypertable on `time`,
    space-partitioned on `farm_id`. CHECK enforces at-least-one
    `value_*` column non-null.

The ConditionContext exposes a per-block "latest observation per
signal_code" view via `app.modules.signals.snapshot.load_snapshot`,
so alert rules and decision-tree predicates can read signal values
the same way they read indices and weather.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-08
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
    # --- signal_definitions --------------------------------------------
    op.create_table(
        "signal_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_kind", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column(
            "categorical_values",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("value_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("value_max", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "attachment_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_signal_definitions_value_kind",
        "signal_definitions",
        "value_kind IN ('numeric','categorical','event','boolean','geopoint')",
    )
    op.create_index(
        "uq_signal_definitions_code_active",
        "signal_definitions",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- signal_assignments --------------------------------------------
    op.create_table(
        "signal_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "signal_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signal_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_signal_assignments_definition_active",
        "signal_assignments",
        ["signal_definition_id"],
        postgresql_where=sa.text("is_active = TRUE AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_signal_assignments_block_active",
        "signal_assignments",
        ["block_id"],
        postgresql_where=sa.text(
            "block_id IS NOT NULL AND is_active = TRUE AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "ix_signal_assignments_farm_active",
        "signal_assignments",
        ["farm_id"],
        postgresql_where=sa.text("farm_id IS NOT NULL AND is_active = TRUE AND deleted_at IS NULL"),
    )

    # --- signal_observations (hypertable) ------------------------------
    # No PK that excludes `time`; UNIQUE on (time, id) is the replay key.
    # Idempotency lives at the application layer (callers generate UUID v7).
    op.create_table(
        "signal_observations",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("signal_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value_numeric", sa.Numeric(14, 4), nullable=True),
        sa.Column("value_categorical", sa.Text(), nullable=True),
        sa.Column("value_event", sa.Text(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        # PostGIS geometry(Point, 4326) — the column type comes from the
        # extension; alembic carries it through as text in the SQL.
        sa.Column("attachment_s3_key", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("time", "id", name="uq_signal_observations_time_id"),
    )
    # Geopoint column added separately so PostGIS handles it.
    op.execute("ALTER TABLE signal_observations ADD COLUMN value_geopoint geometry(Point, 4326)")
    op.create_check_constraint(
        "ck_signal_observations_value_present",
        "signal_observations",
        (
            "(value_numeric IS NOT NULL)::int + (value_categorical IS NOT NULL)::int + "
            "(value_event IS NOT NULL)::int + (value_boolean IS NOT NULL)::int + "
            "(value_geopoint IS NOT NULL)::int >= 1"
        ),
    )

    op.execute(
        """
        SELECT create_hypertable(
            'signal_observations',
            'time',
            chunk_time_interval => INTERVAL '30 days',
            if_not_exists => TRUE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE signal_observations SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'signal_definition_id'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy('signal_observations', INTERVAL '90 days', if_not_exists => TRUE)"
    )

    op.create_index(
        "ix_signal_observations_farm_time",
        "signal_observations",
        ["farm_id", sa.text("time DESC")],
    )
    op.create_index(
        "ix_signal_observations_definition_time",
        "signal_observations",
        ["signal_definition_id", sa.text("time DESC")],
    )
    op.create_index(
        "ix_signal_observations_block_time",
        "signal_observations",
        ["block_id", sa.text("time DESC")],
        postgresql_where=sa.text("block_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_signal_observations_block_time", table_name="signal_observations")
    op.drop_index("ix_signal_observations_definition_time", table_name="signal_observations")
    op.drop_index("ix_signal_observations_farm_time", table_name="signal_observations")
    op.execute("SELECT remove_compression_policy('signal_observations', if_exists => TRUE)")
    op.drop_constraint("ck_signal_observations_value_present", "signal_observations", type_="check")
    op.drop_table("signal_observations")

    op.drop_index("ix_signal_assignments_farm_active", table_name="signal_assignments")
    op.drop_index("ix_signal_assignments_block_active", table_name="signal_assignments")
    op.drop_index("ix_signal_assignments_definition_active", table_name="signal_assignments")
    op.drop_table("signal_assignments")

    op.drop_index("uq_signal_definitions_code_active", table_name="signal_definitions")
    op.drop_constraint("ck_signal_definitions_value_kind", "signal_definitions", type_="check")
    op.drop_table("signal_definitions")
