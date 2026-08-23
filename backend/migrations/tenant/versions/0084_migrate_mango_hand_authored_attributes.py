"""Copy the hand-authored mango attribute values onto the curated definitions.

Public migration 0072 adds `tree_size_class` and `bearing_status` to `mango`
and retires five hand-authored definitions. Two of those five carry values
somebody typed against real blocks, and this migration moves them rather than
stranding them:

`003` "Tree size" folded size and bearing into one three-option list, which
is why no rule could ask about size on its own. It splits:

    01  Young non-productive   -> tree_size_class=small   bearing_status=not_bearing
    02  Young new-productive   -> tree_size_class=small   bearing_status=bearing
    03  Mature productive      -> tree_size_class=large   bearing_status=bearing

`medium` is unreachable from this mapping because `003` had no middle option.
That is not a loss -- the distinction was never recorded -- but it does mean
every migrated block reads as small or large until somebody reviews it.

`004` "Establish method" duplicates the `establishment_method` seeded in
public 0051. Its numeric option codes map onto the curated ones:

    01 Seed -> seed              02 Seedling      -> seedling
    03 Grafted tree -> grafted_tree  04 Rootstock only -> rootstock
    05 Cutting -> cutting        06 Tissue culture -> tissue_culture

Both copies are `ON CONFLICT DO NOTHING` on
`uq_block_crop_attribute_values_pair`, so a block that already carries a
curated value keeps it -- the hand-authored row never overwrites a real one.
Rows are inserted, not updated, so the retired definitions keep their own
values and the step reverses by deleting what it wrote.

Tenants with no mango, or whose definitions were never created, insert
nothing: every statement joins through `public.crop_attribute_definitions`
by code, so an absent definition yields an empty source set.

Revision ID: 0084
Revises: 0083
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (source code, source option, target code, target option)
_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("003", "01", "tree_size_class", "small"),
    ("003", "02", "tree_size_class", "small"),
    ("003", "03", "tree_size_class", "large"),
    ("003", "01", "bearing_status", "not_bearing"),
    ("003", "02", "bearing_status", "bearing"),
    ("003", "03", "bearing_status", "bearing"),
    ("004", "01", "establishment_method", "seed"),
    ("004", "02", "establishment_method", "seedling"),
    ("004", "03", "establishment_method", "grafted_tree"),
    ("004", "04", "establishment_method", "rootstock"),
    ("004", "05", "establishment_method", "cutting"),
    ("004", "06", "establishment_method", "tissue_culture"),
)


# `created_by` / `updated_by` stay NULL: this was not written by a person, and
# a NULL actor is how every other system-written row records that.
_COPY = sa.text(
    """
    INSERT INTO block_crop_attribute_values (
        block_crop_id, definition_id, definition_code, value_option
    )
    SELECT v.block_crop_id, target.id, target.code, :target_option
    FROM block_crop_attribute_values v
    JOIN public.crop_attribute_definitions src
      ON src.id = v.definition_id
     AND src.path = 'mango'
     AND src.code = :source_code
    JOIN public.crop_attribute_definitions target
      ON target.path = 'mango'
     AND target.code = :target_code
    WHERE v.deleted_at IS NULL
      AND v.value_option = :source_option
    ON CONFLICT ON CONSTRAINT uq_block_crop_attribute_values_pair DO NOTHING
    """
)

# Reverses one mapping row exactly: a target value is removed only where the
# same assignment still carries the source value that would have produced it.
#
# `created_by IS NULL` is NOT a usable "written by this migration" test here.
# Every existing value row on prod has a NULL actor -- the attribute-value
# writer has never stamped one -- so a NULL check would delete hand-entered
# values as well. Matching back through the source row is exact instead: a
# value somebody typed on a block whose `003` says something else survives.
_UNDO = sa.text(
    """
    DELETE FROM block_crop_attribute_values target_row
    USING public.crop_attribute_definitions target,
          public.crop_attribute_definitions src,
          block_crop_attribute_values source_row
    WHERE target.id = target_row.definition_id
      AND target.path = 'mango'
      AND target.code = :target_code
      AND target_row.value_option = :target_option
      AND src.id = source_row.definition_id
      AND src.path = 'mango'
      AND src.code = :source_code
      AND source_row.value_option = :source_option
      AND source_row.block_crop_id = target_row.block_crop_id
      AND source_row.deleted_at IS NULL
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for source_code, source_option, target_code, target_option in _MAP:
        bind.execute(
            _COPY,
            {
                "source_code": source_code,
                "source_option": source_option,
                "target_code": target_code,
                "target_option": target_option,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for source_code, source_option, target_code, target_option in _MAP:
        bind.execute(
            _UNDO,
            {
                "source_code": source_code,
                "source_option": source_option,
                "target_code": target_code,
                "target_option": target_option,
            },
        )
