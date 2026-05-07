"""Land-unit polymorphism on `blocks` — add unit_type, parent_unit_id, irrigation_geometry.

PR-1 of the FarmDM rollout. Per the locked decision (memory:
project_farmdm_proposal_decisions), `blocks` stays — we just teach it
about pivots and pivot sectors rather than renaming everything to
`land_units`.

The benefit is that every downstream feature (NDVI computation, alerts,
irrigation scheduling, growth-stage logs) keeps treating the row the
same way regardless of `unit_type`. Pivot-specific geometry (center,
radius, sector start/end angles) lives in a JSONB column that only
makes sense to consumers that care.

Constraints:
  * `unit_type` ∈ {'block', 'pivot', 'pivot_sector'}.
  * `parent_unit_id` is NULL for blocks and pivots; required for
    pivot_sectors. Pivot sectors must reference a pivot on the same
    farm (enforced at the service layer because cross-row CHECK is not
    a thing in PostgreSQL — see 5.5 in data_model.md).
  * Existing rows backfill to ``unit_type = 'block'`` so behavior is
    unchanged for tenants that had blocks before this migration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add unit_type with a server default so existing rows backfill to
    # 'block'. We tighten the column to NOT NULL after the backfill
    # (server_default keeps applying for inserts that omit it).
    op.add_column(
        "blocks",
        sa.Column(
            "unit_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'block'"),
        ),
    )
    op.create_check_constraint(
        "ck_blocks_unit_type",
        "blocks",
        "unit_type IN ('block', 'pivot', 'pivot_sector')",
    )

    # parent_unit_id self-FK for pivot_sector → parent pivot. ON DELETE
    # RESTRICT: deleting a pivot with attached sectors should fail loud
    # rather than orphan the sectors.
    op.add_column(
        "blocks",
        sa.Column(
            "parent_unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_blocks_parent_unit_id",
        "blocks",
        ["parent_unit_id"],
        postgresql_where=sa.text("parent_unit_id IS NOT NULL"),
    )

    # NULL for non-sectors, NOT NULL for sectors. The pivot-on-same-farm
    # invariant is enforced in the service layer (cross-row constraint).
    op.create_check_constraint(
        "ck_blocks_parent_required_for_pivot_sector",
        "blocks",
        "(unit_type = 'pivot_sector' AND parent_unit_id IS NOT NULL)"
        " OR (unit_type IN ('block', 'pivot') AND parent_unit_id IS NULL)",
    )

    # Provider-agnostic JSONB for the pivot/sector geometry knobs (center
    # lat/lon, radius_m, start_angle_deg, end_angle_deg). The actual
    # `boundary` is still the canonical polygon used for indexing and
    # area math; this column carries the parametric description so
    # operations can adjust nozzles/sectors without redrawing the
    # polygon.
    op.add_column(
        "blocks",
        sa.Column(
            "irrigation_geometry",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("blocks", "irrigation_geometry")
    op.drop_constraint("ck_blocks_parent_required_for_pivot_sector", "blocks", type_="check")
    op.drop_index("ix_blocks_parent_unit_id", table_name="blocks")
    op.drop_column("blocks", "parent_unit_id")
    op.drop_constraint("ck_blocks_unit_type", "blocks", type_="check")
    op.drop_column("blocks", "unit_type")
