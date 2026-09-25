"""One platform switch says which decision-tree engine the sweep runs.

    engine = 'old'   the sweep runs `stage = 'live'` trees. Every row today.
    engine = 'beta'  the sweep runs `stage = 'beta'` trees and nothing else.

The two engines never run side by side. A tenant sees the output of one set
of trees, so a problem is never reported twice by two trees that describe it
in different words.

The switch is a one-row table, not a `platform_defaults` key, on purpose. A
key in `platform_defaults` is editable in the generic defaults editor and can
be overridden per tenant, and neither path runs the close-out that has to go
with a flip: the open alerts, recommendations and verdicts the outgoing trees
wrote must be closed in the same transaction as the flip, or the screens show
two engines' output at once. The only writer of this row is
`DecisionEngineSwitch.switch`, which does both.

`last_close_out` holds what the last flip closed, per tenant schema. Alerts
have no history table, so this is the one place the count is kept.

The single row is enforced by `id = 1` plus the primary key, so a second row
cannot be inserted by mistake and two readers never disagree about the
engine.

Revision ID: 0093
Revises: 0092
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0093"
down_revision: str | Sequence[str] | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_engine",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("engine", sa.Text(), nullable=False, server_default=sa.text("'old'")),
        sa.Column("switched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("switched_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_close_out", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_decision_engine_single_row"),
        sa.CheckConstraint("engine IN ('old', 'beta')", name="ck_decision_engine_engine"),
        schema="public",
    )
    op.execute("INSERT INTO public.decision_engine (id, engine) VALUES (1, 'old')")


def downgrade() -> None:
    op.drop_table("decision_engine", schema="public")
