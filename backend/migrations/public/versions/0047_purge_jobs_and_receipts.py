"""Purge jobs + receipts — operational state and tombstones for hard deletes.

Archive/inactivate has always been the only "delete" a farm or block had; the
one true hard delete was tenant purge, and it recorded nothing beyond a single
``platform.tenant_purged`` archive row. These two tables are the state that
platform-admin purge needs:

``purge_jobs``
    Operational. One row per requested purge, updated through its phases so the
    UI can show real progress on a job that deletes thousands of objects, and so
    a crashed run resumes from the last completed phase instead of leaving an
    unknown half-deleted state. Prunable.

``purge_receipts``
    Durable. One row per completed purge, kept indefinitely — after a purge the
    receipt is the only remaining evidence the entity existed, and it carries the
    independent orphan re-scan that says whether the purge actually finished.
    A receipt with ``verification->>'orphans_found' > 0`` is a failed purge.

Both live in ``public`` rather than a tenant schema for the obvious reason: a
tenant purge drops its schema, so a record stored there would delete itself.
This mirrors ``public.backfill_runs`` (0046), the other cross-tenant
platform-admin log.

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_STATES = "'queued', 'running'"
_KINDS = "'block', 'farm', 'tenant', 'tenant_data'"


def upgrade() -> None:
    op.create_table(
        "purge_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # --- what is being purged -----------------------------------------
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Captured at submit time: after the purge there is nothing left to
        # join against, so the label has to be denormalised or the job list
        # renders a bare UUID forever.
        sa.Column("target_label", sa.Text(), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_schema", sa.Text(), nullable=True),
        sa.Column("tenant_slug", sa.Text(), nullable=True),
        # --- state ----------------------------------------------------------
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("phase", sa.Text(), nullable=True),
        # [{"name": "db_rows", "status": "done", "detail": {...}}, ...] — the
        # resume point after a crash, and the progress list the UI renders.
        sa.Column(
            "phases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "preview",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # A dry run walks the whole manifest inside a transaction and rolls
        # back, so its counts are measured rather than estimated.
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        # --- audit ------------------------------------------------------------
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
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_purge_jobs_status",
        ),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="ck_purge_jobs_kind"),
        schema="public",
    )
    op.create_index(
        "ix_purge_jobs_created_at",
        "purge_jobs",
        [sa.text("created_at DESC")],
        schema="public",
    )
    op.create_index(
        "ix_purge_jobs_tenant",
        "purge_jobs",
        ["tenant_id", sa.text("created_at DESC")],
        schema="public",
    )
    # One live purge per target. Two concurrent purges of the same entity would
    # race on the same rows and both report partial counts; the second submit
    # fails on this index instead. Dry runs are excluded — they roll back, so
    # they neither conflict with each other nor with a real purge.
    op.create_index(
        "uq_purge_jobs_active_target",
        "purge_jobs",
        ["kind", "target_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text(f"status IN ({_ACTIVE_STATES}) AND dry_run = false"),
    )

    op.create_table(
        "purge_receipts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # SET NULL, not CASCADE: the receipt has to outlive job pruning — it is
        # the tombstone, the job is just how the work was run.
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.purge_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_label", sa.Text(), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_slug", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # {"db_rows": {...}, "storage_objects": 4192, "stac_items": 4180, ...}
        sa.Column(
            "deleted",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # The independent re-scan. orphans_found > 0 means the purge did not
        # finish, and the UI renders the receipt red with the residue listed.
        sa.Column(
            "verification",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="ck_purge_receipts_kind"),
        schema="public",
    )
    op.create_index(
        "ix_purge_receipts_created_at",
        "purge_receipts",
        [sa.text("created_at DESC")],
        schema="public",
    )
    op.create_index(
        "ix_purge_receipts_target",
        "purge_receipts",
        ["kind", "target_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_purge_receipts_target", table_name="purge_receipts", schema="public")
    op.drop_index("ix_purge_receipts_created_at", table_name="purge_receipts", schema="public")
    op.drop_table("purge_receipts", schema="public")
    op.drop_index("uq_purge_jobs_active_target", table_name="purge_jobs", schema="public")
    op.drop_index("ix_purge_jobs_tenant", table_name="purge_jobs", schema="public")
    op.drop_index("ix_purge_jobs_created_at", table_name="purge_jobs", schema="public")
    op.drop_table("purge_jobs", schema="public")
