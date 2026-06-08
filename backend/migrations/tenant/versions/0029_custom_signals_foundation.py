"""Custom Signals CS-1 foundation — additive schema only.

Ships the four locked design decisions from
[[project-custom-signals-plan]] that can be added without touching the
TimescaleDB hypertable partition key:

  D1 — `signal_templates` + `signal_template_definitions` group N
       definitions for entry/log UX. The engine still sees flat
       per-definition observations.
  D2 — Observations gain `location_mode` ∈ {entity, point_in_entity,
       free_point} + `location_point` (separate from the value-slot
       `value_geopoint`). A trigger enforces ST_Within against the
       referenced block boundary when `location_mode='point_in_entity'`.
  D3 — Definitions gain `aggregation` ∈ {latest, mean, median, max,
       min} + `aggregation_window_days`. The engine uses these to
       collapse observations to a block-level value.
  D8 — Observations gain `template_observation_id` (self-ref). Lead
       row of a template-group stores its own id; siblings point at it.
       No new table; null = standalone observation.

Deferred (per user decision, see CS-1 scope question in session):
  D7 — Rename `time` → `observed_at` on signal_observations. The
       column is the hypertable partition key; renaming requires
       hypertable recreate + 5 raw-SQL call-site updates. Will be
       addressed in CS-1b. New code uses `observed_at` via the
       SQLAlchemy synonym defined in models.py; old code keeps using
       `time` unchanged.

Revision ID: 0029
Revises: 0028   (Track A PR-2 — keep this in lockstep if Track A
                lands after CS-1 instead of before; either order works
                because the two PRs touch disjoint tables.)
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
# Track A PR-2 (`feat/farm-block-config-model`) is in flight at 0028;
# resolve in main once both PRs are merged. The two migrations are
# independent — Track A touches farms/blocks columns, CS-1 touches
# signal_* tables.
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep these in lockstep with the CHECK constraints below + the
# `Aggregation` / `LocationMode` literals in app/modules/signals/schemas.py.
_AGGREGATION_VALUES = ("latest", "mean", "median", "max", "min")
_LOCATION_MODE_VALUES = ("entity", "point_in_entity", "free_point")


def upgrade() -> None:
    # ---- D3: aggregation on signal_definitions -------------------------
    op.add_column(
        "signal_definitions",
        sa.Column(
            "aggregation",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'latest'"),
        ),
    )
    op.add_column(
        "signal_definitions",
        sa.Column(
            # Null = "use all historical observations" (only meaningful for
            # `latest`). The recommendations engine clamps to this window
            # when aggregating numeric values.
            "aggregation_window_days",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_signal_definitions_aggregation",
        "signal_definitions",
        f"aggregation IN {_AGGREGATION_VALUES!r}",
    )
    op.create_check_constraint(
        "ck_signal_definitions_aggregation_window_positive",
        "signal_definitions",
        "aggregation_window_days IS NULL OR aggregation_window_days > 0",
    )

    # ---- D1: signal_templates + junction table -------------------------
    op.create_table(
        "signal_templates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Codes are unique among live rows. Soft-deleted rows free up the
    # code namespace — matches the convention from the
    # `signal_definitions` table. Partial uniqueness requires an
    # Index (CONSTRAINT doesn't accept WHERE in Postgres / SQLAlchemy).
    op.create_index(
        "uq_signal_templates_code_alive",
        "signal_templates",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "signal_template_definitions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "template_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signal_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_definition_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signal_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Display order in the template entry form. 0-indexed within a
        # template; uniqueness within a template enforced below.
        sa.Column("position", sa.Integer(), nullable=False),
        # Whether this definition's value is required when logging via
        # this template. The flat per-definition observation is always
        # nullable — this is a UX-layer hint only.
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_unique_constraint(
        "uq_signal_template_definitions_template_definition",
        "signal_template_definitions",
        ["template_id", "signal_definition_id"],
    )
    op.create_unique_constraint(
        "uq_signal_template_definitions_template_position",
        "signal_template_definitions",
        ["template_id", "position"],
    )

    # ---- D2: location_mode + location_point on observations ------------
    op.add_column(
        "signal_observations",
        sa.Column(
            "location_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'entity'"),
        ),
    )
    # PostGIS geometry — emitted via raw SQL to match the
    # value_geopoint pattern from migration 0017.
    op.execute("ALTER TABLE signal_observations " "ADD COLUMN location_point geometry(Point, 4326)")
    op.create_check_constraint(
        "ck_signal_observations_location_mode",
        "signal_observations",
        f"location_mode IN {_LOCATION_MODE_VALUES!r}",
    )
    # location_point is required iff mode is point_in_entity or
    # free_point; mode=entity must have NO location_point (the
    # observation is conceptually "at the whole entity").
    op.create_check_constraint(
        "ck_signal_observations_location_point_presence",
        "signal_observations",
        "(location_mode = 'entity' AND location_point IS NULL) "
        "OR (location_mode IN ('point_in_entity', 'free_point') "
        "AND location_point IS NOT NULL)",
    )

    # ST_Within trigger for point_in_entity mode. The observation's
    # location_point must lie within the boundary of the referenced
    # block. Fires on INSERT and UPDATE; raises if the point is
    # outside the block polygon or the block has no boundary yet.
    # Skipped for entity and free_point modes (block_id may be NULL
    # for free_point in particular).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION signal_observation_check_point_in_entity()
        RETURNS TRIGGER AS $$
        DECLARE
            block_geom geometry;
        BEGIN
            IF NEW.location_mode <> 'point_in_entity' THEN
                RETURN NEW;
            END IF;
            IF NEW.block_id IS NULL THEN
                RAISE EXCEPTION
                  'signal_observation.location_mode=point_in_entity requires block_id';
            END IF;
            SELECT boundary INTO block_geom FROM blocks WHERE id = NEW.block_id;
            IF block_geom IS NULL THEN
                RAISE EXCEPTION
                  'signal_observation.location_mode=point_in_entity requires '
                  'the referenced block (%) to have a boundary', NEW.block_id;
            END IF;
            IF NOT ST_Within(NEW.location_point, block_geom) THEN
                RAISE EXCEPTION
                  'signal_observation.location_point is not within block % boundary',
                  NEW.block_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_signal_observation_check_point_in_entity
        BEFORE INSERT OR UPDATE OF location_point, location_mode, block_id
        ON signal_observations
        FOR EACH ROW
        EXECUTE FUNCTION signal_observation_check_point_in_entity();
        """
    )

    # ---- D8: template_observation_id self-ref --------------------------
    op.add_column(
        "signal_observations",
        sa.Column(
            "template_observation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    # No FK to (time, id) of the same hypertable — TimescaleDB doesn't
    # support FKs ON a hypertable column from itself, and FKs across
    # hypertables generally are rough. The convention is application-
    # enforced: the lead row's template_observation_id equals its own
    # id; siblings carry the lead row's id. Index for sibling-lookups.
    op.create_index(
        "ix_signal_observations_template_observation_id",
        "signal_observations",
        ["template_observation_id"],
        postgresql_where=sa.text("template_observation_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Reverse order. Trigger + function dropped first; the table
    # alters happen on a clean (no-trigger) hypertable.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_signal_observation_check_point_in_entity "
        "ON signal_observations"
    )
    op.execute("DROP FUNCTION IF EXISTS signal_observation_check_point_in_entity()")

    op.drop_index(
        "ix_signal_observations_template_observation_id",
        table_name="signal_observations",
    )
    op.drop_column("signal_observations", "template_observation_id")

    op.drop_constraint(
        "ck_signal_observations_location_point_presence",
        "signal_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_signal_observations_location_mode",
        "signal_observations",
        type_="check",
    )
    op.execute("ALTER TABLE signal_observations DROP COLUMN IF EXISTS location_point")
    op.drop_column("signal_observations", "location_mode")

    op.drop_table("signal_template_definitions")
    op.drop_table("signal_templates")

    op.drop_constraint(
        "ck_signal_definitions_aggregation_window_positive",
        "signal_definitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_signal_definitions_aggregation",
        "signal_definitions",
        type_="check",
    )
    op.drop_column("signal_definitions", "aggregation_window_days")
    op.drop_column("signal_definitions", "aggregation")
