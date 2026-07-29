"""Backfill runs — operational log for platform-triggered historical loads.

Historical backfill has run in production since #303, but only as a manual
``python -m scripts.backfill_history`` inside a pod. The Celery tasks are
declared ``ignore_result=True``, so nothing is persisted and there is no
status anywhere to read. This table is that missing state: one row per
platform-admin-triggered run, written at submit and updated by the tasks as
they progress.

Lives in ``public`` (not per-tenant) on purpose — the console is a
cross-tenant platform-admin surface, so listing "everything running right
now" must be a single query, not a fan-out over every tenant schema. The
tenant is carried as ``tenant_id`` + ``tenant_schema``, the same shape
``public.decision_trees`` already uses for tenant-owned public rows.

``kind`` separates the two flows that share this log:

  * ``backfill`` — pull raw history from the providers (costs CDSE units).
  * ``indices``  — recompute over data already stored (free).

Concurrency is enforced here rather than in application code: a partial
unique index allows only one non-terminal run per farm, so a duplicate
submit fails on the constraint even under a race. Idempotent tasks make a
concurrent run *safe*, but it would still burn processing units re-fetching
scenes the first run is already pulling.

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Non-terminal states. A farm may hold at most one run in these.
_ACTIVE_STATES = "'queued', 'running'"


def upgrade() -> None:
    op.create_table(
        "backfill_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # --- who / where -------------------------------------------------
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_schema", sa.Text(), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalised for the console list: the farm lives in a tenant
        # schema, and joining across every schema to render a table would
        # defeat the point of keeping this row in public.
        sa.Column("farm_name", sa.Text(), nullable=True),
        sa.Column("tenant_name", sa.Text(), nullable=True),
        # --- what --------------------------------------------------------
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'backfill'")),
        # {"imagery": true, "weather": false} — jsonb rather than an array
        # so an added source is an additive key, not an enum migration.
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        # --- state -------------------------------------------------------
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error", sa.Text(), nullable=True),
        # Per-source counters, written by the tasks as they run so the UI
        # can show real progress instead of jumping 0% -> 100%.
        # {"imagery": {"total": 1750, "done": 718, "failed": 3, ...}, ...}
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # --- audit -------------------------------------------------------
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_email", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_backfill_runs_status",
        ),
        sa.CheckConstraint(
            "kind IN ('backfill', 'indices')",
            name="ck_backfill_runs_kind",
        ),
        sa.CheckConstraint(
            "window_to >= window_from",
            name="ck_backfill_runs_window",
        ),
        schema="public",
    )

    # The console's default view: newest first, optionally filtered by
    # status. One index serves both.
    op.create_index(
        "ix_backfill_runs_created_at",
        "backfill_runs",
        [sa.text("created_at DESC")],
        schema="public",
    )
    op.create_index(
        "ix_backfill_runs_tenant",
        "backfill_runs",
        ["tenant_id", sa.text("created_at DESC")],
        schema="public",
    )

    # Concurrency guard: at most one queued/running run per farm.
    op.create_index(
        "uq_backfill_runs_active_farm",
        "backfill_runs",
        ["farm_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text(f"status IN ({_ACTIVE_STATES})"),
    )


def downgrade() -> None:
    op.drop_index("uq_backfill_runs_active_farm", table_name="backfill_runs", schema="public")
    op.drop_index("ix_backfill_runs_tenant", table_name="backfill_runs", schema="public")
    op.drop_index("ix_backfill_runs_created_at", table_name="backfill_runs", schema="public")
    op.drop_table("backfill_runs", schema="public")
