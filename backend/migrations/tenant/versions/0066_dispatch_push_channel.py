"""Allow `push` on notification_dispatches (S2).

The tenant-side half of the push channel. `public.notification_templates`
gained `push` in public migration 0054; without the same widening here, every
push dispatch row is rejected by the CHECK and the fan-out raises inside a
sync subscriber — which, because sync handler exceptions propagate, would roll
back the alert that triggered it. A missing channel value would therefore not
merely lose the notification, it would lose the alert.

The constraint name is read from the catalog, not reconstructed: Alembic's
naming convention prefixed a constraint whose own name already carried the
prefix, so it is doubled on disk.

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _channel_ck_name(table: str, schema: str | None = None) -> str:
    """Look the channel CHECK's real name up in the catalog.

    Never reconstruct it. The name on disk is already doubled (the convention
    prefixed a constraint whose own name carried the prefix), and passing that
    full name back to ``create_check_constraint`` prefixes it a third time and
    overflows Postgres' 63-character limit into a hash suffix. Reading it means
    the migration works whatever shape a given database ended up with.
    """
    bind = op.get_bind()
    qualified = f"{schema}.{table}" if schema else table
    return str(
        bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:rel AS regclass) AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%channel%' LIMIT 1"
            ),
            {"rel": qualified},
        ).scalar_one()
    )


def upgrade() -> None:
    op.drop_constraint(_channel_ck_name("notification_dispatches"), "notification_dispatches")
    # Short name: the convention expands it to `ck_notification_dispatches_channel`.
    op.create_check_constraint(
        "channel",
        "notification_dispatches",
        "channel IN ('in_app', 'email', 'webhook', 'push')",
    )


def downgrade() -> None:
    # Push rows must go before the narrower CHECK can be re-applied, or the
    # constraint fails to validate against data this migration allowed in.
    op.execute("DELETE FROM notification_dispatches WHERE channel = 'push'")
    op.drop_constraint(_channel_ck_name("notification_dispatches"), "notification_dispatches")
    op.create_check_constraint(
        "channel",
        "notification_dispatches",
        "channel IN ('in_app', 'email', 'webhook')",
    )
