"""Block health definitions move out of code and YAML, into editable rows.

Two tiers of the block health definition could not be changed without a
release:

    platform default   the field defaults of `HealthDefinition` in
                       `app/shared/health_definition.py`
    crop               `app/modules/health/seeds/*.yaml`, copied into
                       `public.crop_health_definitions` at every api start

The startup copy also made the crop rows impossible to edit in the app: it
overwrote a changed row and deleted any row without a file. Decision trees had
the same problem and public migration 0085 solved it the same way: the rows
become the source, and the loader and its files are removed.

This migration:

  1. Adds `public.health_definition_platform`, one row, holding the platform
     default as a full body. The values are the ones `HealthDefinition` has
     always used, so nothing any block reads changes.

     `cell_rollup` is NOT in this body. The platform's rollup rule already
     lives in `public.platform_defaults` as `health.cell_rollup` and
     `health.cell_share_pct` (public 0094), where a tenant overrides it. One
     value in two places would let them disagree.

  2. Lets `public.crop_health_definitions` take rows written by a person:
     `source_path` and `compiled_hash` become nullable, and `updated_by`
     records who saved the row.

  3. Writes the three crop rows the seed files held, for a database that
     never ran the loader (a fresh CI database). ON CONFLICT DO NOTHING, so a
     database that already has them keeps what it has.

Revision ID: 0095
Revises: 0094
Create Date: 2026-10-03
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0095"
down_revision: str | Sequence[str] | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The values `HealthDefinition` has always defaulted to. Written out in full:
# every key the platform tier owns is named, so no tier below it falls back to
# a value that exists only in code.
PLATFORM_BODY: dict[str, object] = {
    "severity_map": {"critical": "critical", "warning": "watch", "info": "healthy"},
    "counted_statuses": ["open", "acknowledged", "snoozed"],
    "snoozed_as": "watch",
    "cell_critical_share": None,
    "recommendation_floor": None,
    "stale_after_hours": 48,
    "no_tree_coverage": "unknown",
}

# The three seed files, as they were on main at 47bb6361.
_CROP_ROWS: tuple[tuple[str, int, str], ...] = (
    (
        "mango",
        72,
        "Perennial tree crop with full decision-tree coverage (22 T_ trees). "
        "Freshness widened to 72h so two missed nightly sweeps do not turn the "
        "orchard Unknown; a mango canopy does not move materially in three days.",
    ),
    (
        "date_palm",
        72,
        "Perennial, slower than mango. Freshness widened to 72h. Tree coverage is "
        "three event-driven trees, so Unknown is expected on quiet blocks and is "
        "left as Unknown rather than being defaulted to healthy.",
    ),
    (
        "potato",
        24,
        "Annual, 90-120 day cycle, with frost and heat trees that are same-day "
        "decisions. Freshness tightened to 24h: one missed nightly sweep reads "
        "Unknown rather than presenting a three-day-old all-clear as current.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "health_definition_platform",
        # One row. The CHECK makes a second row impossible rather than merely
        # unexpected, so a reader never has to ask which one applies.
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Bumped on every save, so a block's "Platform default (v3)" says which
        # generation judged it.
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            # `public.app_now()`, not `now()`: a demo-history replay moves the
            # SQL clock, and a column on the real clock would disagree with it.
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("id = 1", name="single_row"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("jsonb_typeof(definition) = 'object'", name="definition_is_object"),
        schema="public",
    )
    op.get_bind().execute(
        text(
            """
            INSERT INTO public.health_definition_platform (id, definition, version, notes)
            VALUES (1, CAST(:definition AS jsonb), 1, :notes)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "definition": json.dumps(PLATFORM_BODY),
            "notes": "The values the code defaulted to before public migration 0095.",
        },
    )

    op.alter_column("crop_health_definitions", "source_path", nullable=True, schema="public")
    op.alter_column("crop_health_definitions", "compiled_hash", nullable=True, schema="public")
    op.add_column(
        "crop_health_definitions",
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        schema="public",
    )

    for crop_path, hours, notes in _CROP_ROWS:
        op.get_bind().execute(
            text(
                """
                INSERT INTO public.crop_health_definitions
                       (crop_path, definition, version, notes, source_path)
                VALUES (:crop_path, CAST(:definition AS jsonb), 1, :notes, :source_path)
                ON CONFLICT (crop_path) DO NOTHING
                """
            ),
            {
                "crop_path": crop_path,
                "definition": json.dumps({"stale_after_hours": hours}),
                "notes": notes,
                "source_path": f"seeds/{crop_path}.yaml",
            },
        )


def downgrade() -> None:
    # Rows a person wrote have no file behind them. Give them a marker so the
    # NOT NULL can come back; the restored loader will delete them at start.
    op.get_bind().execute(
        text(
            """
            UPDATE public.crop_health_definitions
               SET source_path   = COALESCE(source_path, 'app'),
                   compiled_hash = COALESCE(compiled_hash, '')
            """
        )
    )
    op.drop_column("crop_health_definitions", "updated_by", schema="public")
    op.alter_column("crop_health_definitions", "compiled_hash", nullable=False, schema="public")
    op.alter_column("crop_health_definitions", "source_path", nullable=False, schema="public")
    op.drop_table("health_definition_platform", schema="public")
