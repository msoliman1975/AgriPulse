"""Per-tenant decision-tree sweep cadence, set by a platform admin.

Two things land here.

1. `recommendations.sweep_cadence_hours` in `platform_defaults`. It is a
   tenant-tier key, so a platform admin can override it for one tenant in
   `tenant_settings_overrides` through the existing per-tenant settings
   editor. Category `alert` is an existing category, the same choice
   migration 0026 made for the grid anomaly threshold, so the CHECK
   constraint on `platform_defaults.category` does not move.

   The allowed values are 4, 8, 24 and 168 hours. They are enforced in
   `app/shared/settings/constraints.py`, which every write path runs,
   rather than by a CHECK here, because the value is JSONB and the same
   list has to reach the browser.

2. `public.tenant_dt_dispatch`, one row per tenant, holding the time the
   sweep last enqueued work for that tenant.

Why the second table exists: Celery Beat builds its schedule once at
import time and never rereads it, so a per-tenant cadence cannot live in
the Beat schedule. Beat keeps one hourly tick. The tick reads this table
and enqueues only the tenants whose cadence has elapsed. One hour is
finer than the fastest choice (4 hours), so the tick never limits a
tenant.

`last_dispatched_at` is stamped by the same UPDATE that selects the due
tenants, so two ticks running at once cannot enqueue the same tenant
twice.

Revision ID: 0080
Revises: 0079
Create Date: 2026-09-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "recommendations.sweep_cadence_hours"
_VALUE = 24
_SCHEMA = "number"
_CATEGORY = "alert"
_DESC = (
    "How often the decision-tree sweep evaluates one tenant's blocks, in "
    "hours. One of 4, 8, 24 or 168. A faster cadence costs worker time and "
    "evaluation-trace rows; it does not create duplicate recommendations."
)


def upgrade() -> None:
    op.create_table(
        "tenant_dt_dispatch",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # NULL means "never dispatched", which is due immediately. A tenant
        # created between two ticks therefore gets its first sweep at the
        # next tick instead of waiting a full cadence.
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )

    op.get_bind().execute(
        text(
            """
            INSERT INTO public.platform_defaults
                (key, value, value_schema, description, category)
            VALUES
                (:key, CAST(:value AS jsonb), :value_schema, :description, :category)
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {
            "key": _KEY,
            "value": json.dumps(_VALUE),
            "value_schema": _SCHEMA,
            "description": _DESC,
            "category": _CATEGORY,
        },
    )


def downgrade() -> None:
    # Tenant overrides reference the key with ON DELETE RESTRICT, so they
    # have to go first.
    op.get_bind().execute(
        text("DELETE FROM public.tenant_settings_overrides WHERE key = :key"),
        {"key": _KEY},
    )
    op.get_bind().execute(
        text("DELETE FROM public.platform_defaults WHERE key = :key"),
        {"key": _KEY},
    )
    op.drop_table("tenant_dt_dispatch", schema="public")
