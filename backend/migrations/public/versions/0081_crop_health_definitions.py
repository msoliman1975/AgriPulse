"""Per-crop health definitions — the knowledge base's answer to "healthy".

Phase 5 of moving block health off NDVI thresholds. Phase 2 built the
bounded definition, Phase 4 shipped it behind a flag with ONE definition for
every crop on every farm. This table is where a crop gets its own.

**Why a table and not a column on `crops`.** Targeting is by path, not by
crop. `crops.classification_depth` lets a block carry `mango.keitt`, and a
definition may be authored at either level — the crop for most of them, the
variety where one genuinely differs. A column on `crops` could only ever
hold the shallow one. `crop_varieties` and `crop_variety_strains` would each
need their own column, and the resolution would then read three tables to
answer one question.

**Why no foreign key.** `crop_path` names a row in one of three tables
depending on its depth (`crops.code`, `crop_varieties.path`,
`crop_variety_strains.path`), so there is no single column to point at. The
loader resolves the path against the catalog and refuses to write one it
cannot find, which is the check the FK would have been.

**Resolution is shallow merge, deepest wins per key**, the same rule
`app.modules.farms.crop_thresholds.resolve_thresholds` already uses for the
catalog's other inherited defaults. A definition authored at `mango` and one
at `mango.keitt` both apply to a Keitt block; the variety's keys win, and
the keys it does not name come from the crop. What neither names comes from
`PLATFORM_DEFAULT_DEFINITION`.

**`definition` is validated before it is written, never after.** The loader
runs `app.shared.health_definition.parse_definition` over the JSONB body and
refuses the file on an unknown key. That is deliberate and it is the lesson
from the decision-tree loader: an unknown condition operator there compiles,
publishes and misses for ever, because `evaluate` catches the parse error
and answers "did not match". A misspelled key here would silently mean the
platform default forever. No CHECK constraint can express the schema, so the
loader is the gate and a bad row must never reach the table.

Rows are platform-authored only. There is no tenant column and no API that
writes here: a farm's own override is a tenant-schema concern and arrives in
Phase 6.

Revision ID: 0081
Revises: 0080
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crop_health_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # The targeting key: "mango", "mango.keitt", "mango.keitt.short".
        # Matched against `block_crops.crop_path`, which is denormalised in
        # the tenant schema for exactly this kind of read.
        sa.Column("crop_path", sa.Text(), nullable=False),
        # The bounded definition, as authored. A PARTIAL body is normal and
        # is the point: a crop that only differs in how long a sweep stays
        # believable names `stale_after_hours` and nothing else, and inherits
        # the rest. Storing a fully-populated definition would freeze today's
        # platform defaults into every crop row the day it was written.
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Author's version of this crop's definition, from the YAML. Bumped
        # by hand when the agronomy changes, so a farm that has pinned or
        # overridden one can be told which generation it is holding.
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Why these values. Rendered nowhere yet; it exists so the reasoning
        # travels with the row instead of living only in a YAML comment that
        # the database has never seen.
        sa.Column("notes", sa.Text(), nullable=True),
        # Which seed file produced the row, and the hash of its body. The
        # hash makes the sync idempotent the same way the decision-tree
        # loader's does: same content on disk means no write.
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("compiled_hash", sa.Text(), nullable=False),
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
        # One definition per path. Two rows for "mango" would make the
        # resolution order depend on which one the query happened to read
        # first, and the answer would move between requests.
        sa.UniqueConstraint("crop_path", name="uq_crop_health_definitions_path"),
        # The `name=` fills the convention's `%(constraint_name)s` slot and
        # renders as `ck_crop_health_definitions_<name>`. Passing the full
        # name doubles the prefix and the downgrade then cannot drop it —
        # the bug this repo has hit before, and which is currently live on
        # `platform_alerts`.
        sa.CheckConstraint("crop_path <> ''", name="path_not_empty"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        # The body must be an object. `jsonb_typeof(NULL)` is NULL and NULL
        # is not TRUE, so a plain `= 'object'` would pass a NULL through;
        # the column is NOT NULL, but writing the check this way keeps it
        # correct if that ever changes.
        sa.CheckConstraint("jsonb_typeof(definition) = 'object'", name="definition_is_object"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("crop_health_definitions", schema="public")
