"""Correct the NDWI description, which claimed a meaning its formula cannot give.

Finding D1 of the indices-guide gap audit
(docs/guide/agri-indices-gap-analysis.html).

We compute the McFeeters variant, ``(Green - NIR) / (Green + NIR)``, which
tracks OPEN SURFACE WATER. The seeded ``physical_meaning`` also credited it
with canopy moisture — that is the Gao variant, a different formula on
different bands (NIR/SWIR), which we compute separately and correctly as
``ndmi``. The reference guide devotes a warning note to exactly this collision,
because the two share a name across the literature.

Nothing about the maths or the stored numbers was wrong; only the words. That
is what made it worth fixing rather than leaving: an agronomist reading the
catalog would reasonably have concluded a rising NDWI meant a well-watered
canopy, when it means standing water on the block.

No CALC_VERSION bump — no stored value changes, and no recompute is needed.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CORRECTED = (
    "Open surface water (McFeeters). Positive values are standing water on the "
    "block — ponding, flooding, irrigation tailwater; a healthy canopy reads "
    "well below zero. This is NOT leaf moisture: for water held inside the "
    "canopy use ndmi, which is the Gao/NDII variant on NIR/SWIR1."
)

# Restored verbatim on downgrade, wrong clause and all, so the migration is a
# faithful inverse rather than a second opinion.
_ORIGINAL = (
    "Surface water content / canopy moisture. Positive values "
    "track open water and high leaf water content."
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE public.indices_catalog SET physical_meaning = :meaning WHERE code = 'ndwi'"
        ),
        {"meaning": _CORRECTED},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE public.indices_catalog SET physical_meaning = :meaning WHERE code = 'ndwi'"
        ),
        {"meaning": _ORIGINAL},
    )
