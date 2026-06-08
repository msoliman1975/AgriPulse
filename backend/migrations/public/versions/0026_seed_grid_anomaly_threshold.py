"""Seed the `grid.anomaly_z_threshold` platform default (G-3).

The sub-block grid spatial-anomaly detector flags a cell when its index
mean sits more than ``k`` std-devs below the block's own cell mean. ``k``
was hardcoded to 1.5; this exposes it as a three-tier setting:

    grid_configs.anomaly_z_threshold (per-block)
      -> tenant_settings_overrides['grid.anomaly_z_threshold']
      -> platform_defaults['grid.anomaly_z_threshold']  (this seed)

Category ``alert`` (an existing platform_defaults category) keeps it
alongside the other detection/alerting knobs and avoids widening the
category CHECK constraint. The key auto-appears in the generic
``/admin/defaults`` editor; tenant override is exposed via the
"detection" integrations surface.

Idempotent: ON CONFLICT DO NOTHING, matching 0020.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-07
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "grid.anomaly_z_threshold"
_VALUE = 1.5
_SCHEMA = "number"
_CATEGORY = "alert"
_DESC = (
    "Std-devs below a block's own cell mean before a sub-block grid cell "
    "is flagged as a spatial anomaly. Lower = more sensitive."
)


def upgrade() -> None:
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
    op.get_bind().execute(
        text("DELETE FROM public.platform_defaults WHERE key = :key"),
        {"key": _KEY},
    )
