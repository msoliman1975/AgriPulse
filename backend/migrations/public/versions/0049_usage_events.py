"""usage_events hypertable — product & engagement telemetry.

TEL-1 of docs/proposals/product-telemetry-plan.md.

Why `public` and not the per-tenant schema
------------------------------------------
`audit_events` is per-tenant; this deliberately is not. Every question this
table exists to answer is cross-tenant ("which feature is most used", "which
tenant is going quiet"), platform staff have no `tenant_id` at all (and their
traffic is precisely what we need to *exclude*, which means first recording
it), and one table means one compression policy, one retention policy and one
CAGG set instead of a fresh set per tenant provision. Precedent:
`public.audit_events_archive`, `public.backfill_runs`, `public.decision_trees`.

This is distinct from `audit_events`, which is a *mutation* trail — who changed
what. A user can spend three hours reading Insights and produce not one audit
row. Audit answers "who deleted this block"; this answers "nobody opens
Reports".

Constraint naming
-----------------
`uq_usage_events_time_id` and `ck_usage_events_outcome` are added by raw
``ALTER TABLE`` rather than declared inside ``op.create_table`` on purpose. The
metadata naming convention in `app/shared/db/base.py` is
``ck_%(table_name)s_%(constraint_name)s``, and ``%(constraint_name)s``
substitutes the name *you pass* — so a declared ``name="ck_usage_events_outcome"``
lands in the database as ``ck_usage_events_ck_usage_events_outcome``. This repo
has been bitten three times (0030, 0036, tenant/0054). Raw DDL bypasses the
convention, so the name is exactly what is written here, and
`test_usage_events_migration.py` asserts both names exist.

No primary key: a TimescaleDB hypertable cannot have a PK that excludes the
time partitioning column. `(time, id)` is UNIQUE instead, which is also the
conflict target that makes a duplicated beacon a no-op.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OUTCOMES = "'ok', 'error', 'abandoned', 'cancelled'"


def upgrade() -> None:
    op.create_table(
        "usage_events",
        # --- when + identity of the event itself ---------------------------
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        # Client-generated uuid7. Deliberately has no server_default: the id is
        # the idempotency key for a resent beacon, so it must be stable across
        # resends, which only the client can guarantee. The ingest service
        # mints one when a payload omits it.
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        # --- actor: stamped server-side from RequestContext, never trusted
        #     from the client payload (see TEL-2) -----------------------------
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        # NULL for platform staff, who belong to no tenant.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        # The column that stops our own clicking from dominating every chart.
        sa.Column(
            "is_platform_staff",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # --- what happened -------------------------------------------------
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("feature", sa.Text(), nullable=True),
        # Route TEMPLATE ("/insights/:farmId"), never a resolved path. Resolved
        # paths make grouping impossible and smuggle ids into a text column;
        # the id belongs in farm_id.
        sa.Column("route", sa.Text(), nullable=True),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("flow", sa.Text(), nullable=True),
        sa.Column("step", sa.Text(), nullable=True),
        # --- outcome + timing ----------------------------------------------
        sa.Column("outcome", sa.Text(), nullable=True),
        # Visible dwell for page_leave, perceived latency for an action.
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        # --- context --------------------------------------------------------
        # Joins a client-side api_error to the server log line and the trace.
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("device_kind", sa.Text(), nullable=True),
        sa.Column("viewport_w", sa.SmallInteger(), nullable=True),
        # Allow-listed per event by the ingest service — never free-form. That
        # server-side check is what keeps agronomic and customer content out of
        # telemetry.
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="public",
    )

    # Raw DDL so the names are literal — see the module docstring.
    op.execute(
        "ALTER TABLE public.usage_events "
        "ADD CONSTRAINT uq_usage_events_time_id UNIQUE (time, id)"
    )
    op.execute(
        "ALTER TABLE public.usage_events "
        "ADD CONSTRAINT ck_usage_events_outcome "
        f"CHECK (outcome IS NULL OR outcome IN ({_OUTCOMES}))"
    )

    # 7-day chunks: smaller than audit's 30 because the dashboard's hot window
    # is "last 7/30 days" and narrow chunks keep those scans cheap.
    op.execute(
        """
        SELECT create_hypertable(
            'public.usage_events',
            'time',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )

    # Segment by tenant_id: every dashboard query filters or groups by it.
    op.execute(
        """
        ALTER TABLE public.usage_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'tenant_id',
            timescaledb.compress_orderby = 'time DESC'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy("
        "'public.usage_events', INTERVAL '14 days', if_not_exists => TRUE)"
    )
    # 180 days raw. The continuous aggregates (TEL-6) are kept far longer —
    # that is the point of the rollup. Enforced by policy, not by intent.
    op.execute(
        "SELECT add_retention_policy("
        "'public.usage_events', INTERVAL '180 days', if_not_exists => TRUE)"
    )

    # Partial where the column is sparse, mirroring the audit_events pattern.
    op.create_index(
        "ix_usage_events_tenant_time",
        "usage_events",
        ["tenant_id", sa.text("time DESC")],
        schema="public",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_events_user_time",
        "usage_events",
        ["user_id", sa.text("time DESC")],
        schema="public",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_events_name_time",
        "usage_events",
        ["event_name", sa.text("time DESC")],
        schema="public",
    )
    op.create_index(
        "ix_usage_events_feature_time",
        "usage_events",
        ["feature", sa.text("time DESC")],
        schema="public",
        postgresql_where=sa.text("feature IS NOT NULL"),
    )
    # Ascending time: a session timeline is read forwards (TEL/B5).
    op.create_index(
        "ix_usage_events_session",
        "usage_events",
        ["session_id", "time"],
        schema="public",
    )
    op.create_index(
        "ix_usage_events_correlation",
        "usage_events",
        ["correlation_id"],
        schema="public",
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Policies must go before the table; a live job holding the hypertable
    # makes the DROP fail.
    op.execute("SELECT remove_retention_policy('public.usage_events', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('public.usage_events', if_exists => TRUE)")
    # DROP TABLE takes the indexes and constraints with it, which is also why
    # downgrade never names a constraint — see the module docstring.
    op.drop_table("usage_events", schema="public")
