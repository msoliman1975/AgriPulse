"""Observer verification: named runs and their per-scene results.

A verify recomputes a scene's statistics from the stored raster and compares
them against what is in ``block_index_aggregates``. It **never writes to the
pipeline's tables** — a drift verdict is a signal to open the Backfill
Console, not something Observer silently repairs. These two tables hold the
verification's own state and findings.

**Why a run table rather than a request/response.** A full verify of one year
across a 36-block farm is ~2,500 heavy-task executions. That is not a button
that returns a response, so multi-scene verify follows the Backfill Console's
model exactly: a named run with progress, a cancel, and a partial unique index
enforcing one active run per farm.

The one-per-farm guard is the same reasoning backfill uses — a second run
would re-read the same COGs while the first is still working. And ``cancel``
ships with the feature rather than after it: a run that can hang needs an
operator escape hatch that is not "edit the table", which is the lesson #332
taught when a stuck run locked a farm indefinitely.

``observer_verifications`` is keyed by run so a finished run is a browsable
report, and repeat views cost nothing. Single-scene verification (the
synchronous path from the scene-detail page) writes a row with
``run_id IS NULL``.

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_STATUSES = "'queued', 'running', 'succeeded', 'failed', 'cancelled'"
# `fast` reads the per-index COGs, which already have masking baked in, so it
# verifies aggregation only. `full` re-reads the raw bands and re-runs the
# mask and the formulas, so it verifies the whole chain. The distinction is
# stored because a "match" means different things under each.
_MODES = "'fast', 'full'"
_VERDICTS = "'match', 'drift', 'source_missing', 'error'"


def upgrade() -> None:
    op.create_table(
        "observer_verify_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL = every block in the farm. Stored as the operator chose it, so
        # the report says what was asked for rather than what it expanded to.
        sa.Column("block_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by_email", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN ({_RUN_STATUSES})", name="status"),
        sa.CheckConstraint(f"mode IN ({_MODES})", name="mode"),
        sa.CheckConstraint("window_to > window_from", name="window_forwards"),
    )

    # One active run per farm. Partial, so finished runs pile up freely and
    # only the in-flight one occupies the farm.
    op.create_index(
        "uq_observer_verify_runs_active_farm",
        "observer_verify_runs",
        ["farm_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_observer_verify_runs_created",
        "observer_verify_runs",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "observer_verifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # NULL for a single-scene verification run straight from scene detail.
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observer_verify_runs.id", ondelete="CASCADE", name="run_id"),
            nullable=True,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        # Worst verdict across the indices on this scene, so a run can be
        # filtered to "show me the drift" without unpacking the JSONB.
        sa.Column("verdict", sa.Text(), nullable=False),
        # {index_code: {stored_mean, recomputed_mean, delta_mean,
        #               stored_valid, recomputed_valid, verdict}}
        sa.Column(
            "per_index",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("calc_version_stored", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"verdict IN ({_VERDICTS})", name="verdict"),
        sa.CheckConstraint(f"mode IN ({_MODES})", name="mode"),
    )
    op.create_index(
        "ix_observer_verifications_run",
        "observer_verifications",
        ["run_id", "verdict"],
    )
    op.create_index(
        "ix_observer_verifications_scene",
        "observer_verifications",
        ["block_id", "product_id", "scene_time", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_observer_verifications_scene", table_name="observer_verifications")
    op.drop_index("ix_observer_verifications_run", table_name="observer_verifications")
    op.drop_table("observer_verifications")
    op.drop_index("ix_observer_verify_runs_created", table_name="observer_verify_runs")
    op.drop_index("uq_observer_verify_runs_active_farm", table_name="observer_verify_runs")
    op.drop_table("observer_verify_runs")
