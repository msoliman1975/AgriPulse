"""Crop attribute definitions — platform-curated typed fields per crop.

Some crops are not established from seed. A mango block is planted as a
grafted nursery tree; a date palm from an offshoot or a tissue-culture
plantlet; a tomato from a nursery seedling. In every one of those cases the
crop → block assignment needs facts that ``block_crops`` has no column for —
establishment method, transplant date, age and size at transplant, rootstock,
nursery source — and the *shape* of those facts differs per crop.

This table is the definition side of that: a platform-curated, typed field
catalog attached to the crop taxonomy. Values live per assignment in the
tenant schema (see tenant migration 0055).

Definitions attach at any level of the taxonomy — ``crop_id`` always, plus
optionally ``crop_variety_id`` or ``crop_variety_strain_id`` — and resolve
**deepest-wins by ``code``**, the same rule ``size_classes`` and
``default_thresholds`` already use (``farms/crop_attributes.resolve``). A
deeper row with the same ``code`` replaces the inherited one wholesale, so a
variety can narrow a range or shorten an option list, and setting
``is_active = false`` on a deeper row suppresses an inherited attribute
entirely.

Gating (``show_when`` / ``required_when``) is deliberately one level deep and
non-recursive — ``{"code": "establishment_method", "in": [...]}`` referencing
another attribute on the same assignment. That covers "transplant_date is
required only when the block was transplanted" without growing a second rules
engine next to the decision-tree evaluator.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUE_TYPES = "'integer', 'decimal', 'text', 'boolean', 'date', 'single_select', 'multi_select'"
_NUMERIC_TYPES = "'integer', 'decimal'"
_SELECT_TYPES = "'single_select', 'multi_select'"


def upgrade() -> None:
    op.create_table(
        "crop_attribute_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # --- taxonomy attachment -------------------------------------------
        # crop_id is always set (it scopes the resolve walk); the two deeper
        # columns say which level this row attaches to. RESTRICT matches the
        # rest of the catalog: a crop with definitions cannot be hard-deleted.
        sa.Column(
            "crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.crops.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "crop_variety_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.crop_varieties.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "crop_variety_strain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.crop_variety_strains.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Denormalised canonical path of the attachment node ("mango",
        # "mango.sukkary", "mango.alphonso.short"). Same trick as
        # crop_varieties.path: it makes the deepest-wins resolve a prefix
        # match instead of three joins, and it is what the value rows and the
        # decision-tree authoring warning compare against.
        sa.Column("path", sa.Text(), nullable=False),
        # --- identity -------------------------------------------------------
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        # --- type + constraints ---------------------------------------------
        sa.Column("value_type", sa.Text(), nullable=False),
        sa.Column("unit_en", sa.Text(), nullable=True),
        sa.Column("unit_ar", sa.Text(), nullable=True),
        sa.Column("value_min", sa.Numeric(14, 4), nullable=True),
        sa.Column("value_max", sa.Numeric(14, 4), nullable=True),
        sa.Column("decimal_places", sa.Integer(), nullable=True),
        sa.Column("text_max_length", sa.Integer(), nullable=True),
        # [{"code", "name_en", "name_ar", "sort_order"}, ...] — validated in
        # the service; the CHECK only pins presence/absence per value_type.
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # --- requiredness + gating ------------------------------------------
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("required_when", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("show_when", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # --- presentation ----------------------------------------------------
        sa.Column("group_code", sa.Text(), nullable=True),
        sa.Column("group_name_en", sa.Text(), nullable=True),
        sa.Column("group_name_ar", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_reportable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # --- audit ------------------------------------------------------------
        # The full TimestampedMixin column set (data_model § 1.4). The ORM
        # model mixes it in, so omitting created_by / updated_by / deleted_at
        # makes every SELECT fail with UndefinedColumn.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"value_type IN ({_VALUE_TYPES})",
            name="value_type",
        ),
        # A strain-level row must also carry its variety, so the path walk
        # never has a hole in the middle.
        sa.CheckConstraint(
            "crop_variety_strain_id IS NULL OR crop_variety_id IS NOT NULL",
            name="level",
        ),
        # Options exist for exactly the select types. Without this an author
        # can save a single_select with no options, which renders as an empty
        # dropdown that can never satisfy its own required_when.
        sa.CheckConstraint(
            f"(value_type IN ({_SELECT_TYPES})) = (options IS NOT NULL)",
            name="options",
        ),
        # Numeric-only facets. A text field with a value_min is not a
        # validation rule anyone implements — it is a mistake.
        sa.CheckConstraint(
            f"value_type IN ({_NUMERIC_TYPES})"
            " OR (value_min IS NULL AND value_max IS NULL"
            "     AND decimal_places IS NULL AND unit_en IS NULL AND unit_ar IS NULL)",
            name="numeric_facets",
        ),
        sa.CheckConstraint(
            "value_min IS NULL OR value_max IS NULL OR value_min <= value_max",
            name="range",
        ),
        sa.CheckConstraint(
            "value_type = 'text' OR text_max_length IS NULL",
            name="text_max_length",
        ),
        sa.CheckConstraint(
            "decimal_places IS NULL OR (decimal_places >= 0 AND decimal_places <= 4)",
            name="decimal_places",
        ),
        schema="public",
    )

    # One definition per code per taxonomy node. Two rows with the same code
    # at the same level would make the deepest-wins resolve order-dependent.
    op.create_index(
        "uq_crop_attribute_definitions_path_code",
        "crop_attribute_definitions",
        ["path", "code"],
        unique=True,
        schema="public",
    )
    # The resolve walk: every definition for a crop, ordered for display.
    op.create_index(
        "ix_crop_attribute_definitions_crop",
        "crop_attribute_definitions",
        ["crop_id", "sort_order"],
        schema="public",
    )
    # The decision-tree condition builder asks "which attributes exist at all",
    # across crops, filtered to active.
    op.create_index(
        "ix_crop_attribute_definitions_code",
        "crop_attribute_definitions",
        ["code"],
        schema="public",
        postgresql_where=sa.text("is_active"),
    )
    # Same `updated_at` maintenance every other catalog table gets.
    op.execute(
        "CREATE TRIGGER trg_crop_attribute_definitions_updated_at "
        "BEFORE UPDATE ON public.crop_attribute_definitions "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crop_attribute_definitions_code",
        table_name="crop_attribute_definitions",
        schema="public",
    )
    op.drop_index(
        "ix_crop_attribute_definitions_crop",
        table_name="crop_attribute_definitions",
        schema="public",
    )
    op.drop_index(
        "uq_crop_attribute_definitions_path_code",
        table_name="crop_attribute_definitions",
        schema="public",
    )
    op.drop_table("crop_attribute_definitions", schema="public")
