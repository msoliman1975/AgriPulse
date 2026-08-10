"""Dispatches can name a visit, and can be per-device (S2).

Two changes, both needed before a scout's phone can announce a visit.

**visit_id.** A visit raised from an ad-hoc dispatch has neither an alert nor a
recommendation behind it, so the existing "exactly one of (alert_id,
recommendation_id)" CHECK made it impossible to record that we notified anyone
about it. The CHECK becomes exactly-one-of-three.

**Per-device uniqueness — a real bug fix.** The idempotency indexes were
``UNIQUE (alert_id, channel, recipient_user_id) WHERE status IN
('pending','sent')``, which is correct while a channel means one delivery per
person. Push does not: it writes one row per registered device, because "did it
reach them" is a per-device question. A scout with a phone *and* a tablet would
therefore violate the index on the second insert — and because the fan-out runs
in a sync subscriber, that IntegrityError would propagate and **roll back the
alert that triggered it**. A second handset would have silently cost the farm
an alert.

The fix adds ``recipient_address`` (which for push is the device, for email the
address, for in_app NULL) to each index, with ``NULLS NOT DISTINCT`` so in_app
rows — whose address is NULL — keep the one-per-user idempotency they have
today. Without that modifier Postgres treats every NULL as unique and in_app
would silently lose its guard, which is the opposite of the intent here.

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "status = ANY (ARRAY['pending'::text, 'sent'::text])"


def _source_ck_name() -> str:
    """Read the source CHECK's real name. Never reconstruct it — the name on
    disk is already doubled by the naming convention."""
    return str(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST('notification_dispatches' AS regclass) "
                "AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%recommendation_id IS NOT NULL%'"
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    op.add_column(
        "notification_dispatches",
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.drop_constraint(_source_ck_name(), "notification_dispatches")
    op.create_check_constraint(
        "source",
        "notification_dispatches",
        "(alert_id IS NOT NULL)::int + (recommendation_id IS NOT NULL)::int "
        "+ (visit_id IS NOT NULL)::int = 1",
    )

    # Rebuild both idempotency indexes with the device/address in the key.
    op.drop_index("uq_notification_dispatches_alert_chan_user_active")
    op.drop_index("uq_notification_dispatches_rec_chan_user_active")
    op.execute(
        "CREATE UNIQUE INDEX uq_notification_dispatches_alert_chan_user_active "
        "ON notification_dispatches "
        "(alert_id, channel, recipient_user_id, recipient_address) "
        "NULLS NOT DISTINCT "
        f"WHERE ({_LIVE} AND alert_id IS NOT NULL)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notification_dispatches_rec_chan_user_active "
        "ON notification_dispatches "
        "(recommendation_id, channel, recipient_user_id, recipient_address) "
        "NULLS NOT DISTINCT "
        f"WHERE ({_LIVE} AND recommendation_id IS NOT NULL)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notification_dispatches_visit_chan_user_active "
        "ON notification_dispatches "
        "(visit_id, channel, recipient_user_id, recipient_address) "
        "NULLS NOT DISTINCT "
        f"WHERE ({_LIVE} AND visit_id IS NOT NULL)"
    )


def downgrade() -> None:
    # Visit dispatches have no home in the narrower shape.
    op.execute("DELETE FROM notification_dispatches WHERE visit_id IS NOT NULL")
    op.drop_index("uq_notification_dispatches_visit_chan_user_active")
    op.drop_index("uq_notification_dispatches_rec_chan_user_active")
    op.drop_index("uq_notification_dispatches_alert_chan_user_active")
    op.execute(
        "CREATE UNIQUE INDEX uq_notification_dispatches_alert_chan_user_active "
        "ON notification_dispatches (alert_id, channel, recipient_user_id) "
        f"WHERE ({_LIVE} AND alert_id IS NOT NULL)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notification_dispatches_rec_chan_user_active "
        "ON notification_dispatches (recommendation_id, channel, recipient_user_id) "
        f"WHERE ({_LIVE} AND recommendation_id IS NOT NULL)"
    )
    op.drop_constraint(_source_ck_name(), "notification_dispatches")
    op.create_check_constraint(
        "source",
        "notification_dispatches",
        "(alert_id IS NOT NULL)::int + (recommendation_id IS NOT NULL)::int = 1",
    )
    op.drop_column("notification_dispatches", "visit_id")
