"""How a block's health class is built from its cells, set per tenant.

A cell-scoped decision tree writes one verdict per grid cell. The block's
class has to come from those cells somehow, and tenants disagree on how:

    worst        the worst cell decides. One red cell makes a red block.
                 Cautious, and noisy on a large block. The default, because
                 it is what every block has been judged by until now.
    share        the worst status that covers at least a share of the cells
                 decides. One bad cell shows on the map but does not
                 recolour the block.
    most_common  the status that covers the most cells decides. Calm, and
                 able to hide a real hotspot.

Two tenant-tier keys in `platform_defaults`, so a tenant admin writes them
through the existing tenant settings path and its constraint checks
(`app/shared/settings/constraints.py`):

    health.cell_rollup      'worst' | 'share' | 'most_common'
    health.cell_share_pct   1..100, read only by 'share'

The health definition resolver reads them as a tier between the platform
default and the crop catalogue (`app/modules/health/service.py`). A crop row
or a farm override that names `cell_rollup` still wins.

Category `alert`, the one the grid anomaly threshold and the sweep cadence
already use, so the CHECK on `platform_defaults.category` does not move.

Revision ID: 0094
Revises: 0093
Create Date: 2026-09-24
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0094"
down_revision: str | Sequence[str] | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROWS: tuple[tuple[str, object, str, str], ...] = (
    (
        "health.cell_rollup",
        "worst",
        "string",
        "How a block's health class is built from its grid cells: 'worst' (the "
        "worst cell decides), 'share' (the worst status covering at least "
        "health.cell_share_pct of the cells decides) or 'most_common' (the "
        "status covering the most cells decides).",
    ),
    (
        "health.cell_share_pct",
        20,
        "number",
        "For health.cell_rollup = 'share': the percent of a block's cells a "
        "status must cover, counting worse statuses too, before the block "
        "takes that status. 1 to 100.",
    ),
)


def upgrade() -> None:
    for key, value, schema, description in _ROWS:
        op.get_bind().execute(
            text(
                """
                INSERT INTO public.platform_defaults
                    (key, value, value_schema, description, category)
                VALUES (:key, CAST(:value AS jsonb), :value_schema, :description, 'alert')
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "value": json.dumps(value),
                "value_schema": schema,
                "description": description,
            },
        )


def downgrade() -> None:
    keys = [row[0] for row in _ROWS]
    # Tenant overrides reference the key with ON DELETE RESTRICT, so they
    # have to go first.
    op.get_bind().execute(
        text("DELETE FROM public.tenant_settings_overrides WHERE key = ANY(:keys)"),
        {"keys": keys},
    )
    op.get_bind().execute(
        text("DELETE FROM public.platform_defaults WHERE key = ANY(:keys)"),
        {"keys": keys},
    )
