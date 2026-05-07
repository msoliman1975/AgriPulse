"""tenant_subscriptions enrichment — plan_type + price_per_feddan + trial dates.

PR-8 of FarmDM rollout. Adds the four fields the proposal called out:

  * `plan_type` — friendlier name than `tier`. We *keep* `tier` (the
    enum the rest of the platform conditions on) and add `plan_type`
    as a free-form label so marketing-side renames don't ripple
    through the codebase.
  * `price_per_feddan` — used by the future billing UI.
  * `trial_start` / `trial_end` — the in-trial flag is derived in app
    code rather than stored, so the DB is the source of truth for
    raw dates only.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_subscriptions",
        sa.Column("plan_type", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenant_subscriptions",
        sa.Column("price_per_feddan", sa.Numeric(10, 2), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenant_subscriptions",
        sa.Column("trial_start", sa.Date(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenant_subscriptions",
        sa.Column("trial_end", sa.Date(), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_trial_window",
        "tenant_subscriptions",
        "trial_start IS NULL OR trial_end IS NULL OR trial_end >= trial_start",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenant_subscriptions_trial_window",
        "tenant_subscriptions",
        schema="public",
        type_="check",
    )
    op.drop_column("tenant_subscriptions", "trial_end", schema="public")
    op.drop_column("tenant_subscriptions", "trial_start", schema="public")
    op.drop_column("tenant_subscriptions", "price_per_feddan", schema="public")
    op.drop_column("tenant_subscriptions", "plan_type", schema="public")
