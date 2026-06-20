"""Track cascade-provenance on weather + imagery subscriptions.

Adds ``deactivated_by_cascade`` to ``weather_subscriptions`` and
``imagery_aoi_subscriptions`` so block/farm REACTIVATION can restore only
the subscriptions that block/farm INACTIVATION turned off — without
re-enabling a subscription an operator had manually paused.

Deactivation (``farms.cascade.apply_block_cascade``) now stamps this flag
TRUE when it flips a sub to ``is_active = FALSE``; reactivation
(``farms.cascade.restore_block_cascade``) re-activates rows where the flag
is TRUE and clears it. Default FALSE so existing / manually-managed rows
are untouched (flag starts FALSE = "not cascade-deactivated").

Fixes the asymmetric-cascade bug where deactivating then reactivating a
block (or farm) left its weather/imagery subscriptions silently off.

Data-safe: additive column with a server default; no existing row changes
meaning.

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("weather_subscriptions", "imagery_aoi_subscriptions")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "deactivated_by_cascade",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "deactivated_by_cascade")
