"""Board PR-2 — resources foundation (workers + equipment).

Adds two tables to the tenant schema:

  * `resources` — flat catalog of assignable people and equipment per
    farm. One table, discriminator column `kind ∈ {worker,equipment}`.
    Workers carry `role` (agronomist | operator | scout | field_worker
    | manager) and optional `phone`; equipment carries `equipment_type`
    (tractor | sprayer | irrigation_pump | harvester | other). A CHECK
    constraint enforces kind ↔ specific-fields exclusivity so we can't
    save an equipment row with a role attached.

  * `activity_resources` — composite-PK join from `plan_activities` to
    `resources`. ON DELETE CASCADE on both sides: deleting an activity
    drops its assignments, archiving a resource doesn't (we archive
    via `archived_at`, not DELETE).

A partial unique index on (farm_id, kind, lower(name)) where
`archived_at IS NULL` prevents two active resources with the same name.
Archived rows keep their name so history stays readable.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
# Chains after 0030a (plan_activities board columns) — see the comment
# in that file for the parallel-authoring renumber.
down_revision: str | None = "0030a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep in lockstep with app/modules/resources/schemas.py literals.
_KIND_VALUES = ("worker", "equipment")
_ROLE_VALUES = ("agronomist", "operator", "scout", "field_worker", "manager")
_EQUIPMENT_TYPE_VALUES = (
    "tractor",
    "sprayer",
    "irrigation_pump",
    "harvester",
    "other",
)


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "farm_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("equipment_type", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            f"kind IN {_KIND_VALUES!r}",
            name="kind",
        ),
        sa.CheckConstraint(
            "(kind = 'worker' AND role IS NOT NULL AND equipment_type IS NULL)"
            " OR "
            "(kind = 'equipment' AND equipment_type IS NOT NULL AND role IS NULL AND phone IS NULL)",
            name="kind_fields_exclusive",
        ),
        sa.CheckConstraint(
            f"role IS NULL OR role IN {_ROLE_VALUES!r}",
            name="role",
        ),
        sa.CheckConstraint(
            f"equipment_type IS NULL OR equipment_type IN {_EQUIPMENT_TYPE_VALUES!r}",
            name="equipment_type",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="name_nonempty",
        ),
    )

    op.create_index(
        "ix_resources_farm_kind_archived",
        "resources",
        ["farm_id", "kind", "archived_at"],
    )

    # Active rows must have unique (farm_id, kind, lowercased name).
    # Archived rows keep their name so historical activity assignments
    # still read correctly. Expression index → use raw SQL.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_resources_farm_kind_active_name
        ON resources (farm_id, kind, lower(name))
        WHERE archived_at IS NULL AND deleted_at IS NULL
        """
    )

    op.create_table(
        "activity_resources",
        sa.Column(
            "activity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plan_activities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "resource_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_activity_resources_resource_id",
        "activity_resources",
        ["resource_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activity_resources_resource_id", table_name="activity_resources"
    )
    op.drop_table("activity_resources")
    op.execute("DROP INDEX IF EXISTS uq_resources_farm_kind_active_name")
    op.drop_index("ix_resources_farm_kind_archived", table_name="resources")
    op.drop_table("resources")
