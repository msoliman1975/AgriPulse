"""Canopy size-class lookup on the crop taxonomy.

Adds a nullable ``size_classes`` JSONB to ``public.crops`` and a
``size_classes_override`` to ``public.crop_varieties`` /
``public.crop_variety_strains``. Shape is ``{"classes": [{code, name_en,
name_ar, order}]}`` (validated in app code), resolved deepest-wins like
``phenology_stages``. Surfaced as the per-block canopy-size dropdown and
exposed to the recommendation engine.

All adds are nullable -> data-safe; downgrade drops the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crops",
        sa.Column("size_classes", JSONB(), nullable=True),
        schema="public",
    )
    op.add_column(
        "crop_varieties",
        sa.Column("size_classes_override", JSONB(), nullable=True),
        schema="public",
    )
    op.add_column(
        "crop_variety_strains",
        sa.Column("size_classes_override", JSONB(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("crop_variety_strains", "size_classes_override", schema="public")
    op.drop_column("crop_varieties", "size_classes_override", schema="public")
    op.drop_column("crops", "size_classes", schema="public")
