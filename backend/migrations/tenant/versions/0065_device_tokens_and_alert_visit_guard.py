"""Push device tokens, plus the alert-side dispatch guard (S2).

Two changes that belong together because both exist to make automatic dispatch
safe.

**device_tokens** — where to send a push. One row per (user, device); a scout
with a phone and a tablet has two. Tenant-scoped like
``notification_dispatches``, which is what it will be joined against.

**scouting_visits.alert_id guard** — tenant migration 0064 added a partial
UNIQUE on ``recommendation_id`` so the daily evaluator cannot queue a fresh
visit every morning, but left the alert path unguarded. That was an oversight
rather than a decision: alerts reach the dispatcher through
``AlertOpenedV1``, and an in-process event that is redelivered — or a
subscriber that runs twice during a retry — would raise a second visit for the
same alert. The same partial UNIQUE closes it.

Note the asymmetry is deliberate on the *cancelled/expired* exclusion: a block
whose alert closed and re-opened gets a **new** ``alert_id``, so a genuinely
new problem still dispatches a genuinely new visit.

Revision ID: 0065
Revises: 0064
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # public.users.id — no FK, the same cross-schema logical reference
        # tenant_memberships and farm_scopes already use.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'android'")),
        sa.Column("app_version", sa.Text(), nullable=True),
        # Device locale at registration. The push body is rendered server-side
        # from the user's preference, so this is diagnostic only — it answers
        # "did we send Arabic to a device set to English" after the fact.
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Set on logout, on an FCM `UNREGISTERED`, or by the offboarding flow.
        # Revoking rather than deleting keeps a record that the device existed,
        # which matters when someone asks why a phone stopped buzzing.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("platform IN ('android', 'ios', 'web')", name="platform"),
    )
    # A token identifies exactly one device installation. FCM reassigns tokens
    # between installs, so re-registering an existing token must move it to the
    # new user rather than create a second row that pushes to a stale owner.
    op.create_index("uq_device_tokens_token", "device_tokens", ["token"], unique=True)
    # The fan-out: every live device for a recipient.
    op.create_index(
        "ix_device_tokens_user_live",
        "device_tokens",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL AND deleted_at IS NULL"),
    )

    op.create_index(
        "uq_scouting_visits_live_alert",
        "scouting_visits",
        ["alert_id"],
        unique=True,
        postgresql_where=sa.text("alert_id IS NOT NULL AND status NOT IN ('cancelled', 'expired')"),
    )

    op.execute(
        "CREATE TRIGGER trg_device_tokens_updated_at "
        "BEFORE UPDATE ON device_tokens "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_device_tokens_updated_at ON device_tokens")
    op.drop_index("uq_scouting_visits_live_alert", table_name="scouting_visits")
    op.drop_index("ix_device_tokens_user_live", table_name="device_tokens")
    op.drop_index("uq_device_tokens_token", table_name="device_tokens")
    op.drop_table("device_tokens")
