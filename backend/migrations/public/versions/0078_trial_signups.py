"""Trial signups — the queue behind the self-serve trial front door.

One row per person who asked for a trial, from the moment they submit the
marketing form to the moment their tenant exists. The row is the evidence
trail: every state change is visible here, so "what happened to my signup"
is answerable without reading logs.

Lives in `public` because at signup time there is no tenant to own it.

`tenant_id` is a real foreign key — both sides are in `public`, so the rule
against tenant-to-public keys does not apply here.

Nothing is provisioned without a platform admin approving the row. See
`docs/proposals/self-serve-trial-flow.md`.

Revision ID: 0078
Revises: 0077
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in one place so the model, the service and the CHECK cannot drift.
_STATUSES = (
    "pending_verification",
    "awaiting_approval",
    "paused",
    "approved",
    "provisioning",
    "provisioned",
    "rejected",
    "routed_to_existing",
    "failed",
    "expired",
)


def upgrade() -> None:
    op.create_table(
        "trial_signups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'pending_verification'")
        ),
        # --- what they told us -------------------------------------------
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        # Stored separately so the duplicate and disposable checks are an
        # index lookup, not a substring scan.
        sa.Column("email_domain", sa.Text(), nullable=False),
        sa.Column("organisation", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=False, server_default=sa.text("'en'")),
        # --- verification -------------------------------------------------
        # Only the hash is stored. A leaked table must not yield a working
        # verification link.
        sa.Column("verification_token_hash", sa.Text(), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        # The visitor's own opaque handle for the status page. Unguessable,
        # and carries no information if it leaks.
        sa.Column("status_handle", sa.Text(), nullable=False),
        # --- review --------------------------------------------------------
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "cap_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        # --- provisioning ----------------------------------------------------
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "provisioning_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        # --- provenance -------------------------------------------------------
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("chase_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        # The five TimestampedMixin columns. The model inherits the mixin, so
        # every SELECT it builds names all five — a table missing any of them
        # fails at query time, not at migration time.
        #
        # `created_by` stays NULL for every trial signup: the row is written by
        # an anonymous visitor, and the named actor appears on `reviewed_by`
        # when a platform admin decides it.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")",
            # Full name, matching every other migration in this tree.
            # `op.create_table` does not apply the ORM naming convention,
            # so a short name here lands in Postgres verbatim.
            name="ck_trial_signups_status",
        ),
        schema="public",
    )

    op.create_index(
        "ix_trial_signups_status_created",
        "trial_signups",
        ["status", "created_at"],
        schema="public",
    )
    op.create_index(
        "ix_trial_signups_email_domain",
        "trial_signups",
        ["email_domain"],
        schema="public",
    )
    op.create_index(
        "uq_trial_signups_status_handle",
        "trial_signups",
        ["status_handle"],
        unique=True,
        schema="public",
    )
    # One live request per address, and one per company. A request that was
    # rejected, expired or already provisioned no longer blocks a new one —
    # a customer whose trial ended must be able to ask again.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_trial_signups_live_email
            ON public.trial_signups (lower(email))
            WHERE status IN ('pending_verification', 'awaiting_approval',
                             'paused', 'approved', 'provisioning')
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_trial_signups_live_domain
            ON public.trial_signups (email_domain)
            WHERE status IN ('awaiting_approval', 'paused', 'approved',
                             'provisioning')
        """
    )


def downgrade() -> None:
    op.drop_index("uq_trial_signups_live_domain", table_name="trial_signups", schema="public")
    op.drop_index("uq_trial_signups_live_email", table_name="trial_signups", schema="public")
    op.drop_index("uq_trial_signups_status_handle", table_name="trial_signups", schema="public")
    op.drop_index("ix_trial_signups_email_domain", table_name="trial_signups", schema="public")
    op.drop_index("ix_trial_signups_status_created", table_name="trial_signups", schema="public")
    op.drop_table("trial_signups", schema="public")
