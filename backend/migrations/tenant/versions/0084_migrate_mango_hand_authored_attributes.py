"""Copy the hand-authored mango attribute values onto the curated definitions.

Public migration 0072 adds `tree_size_class` and `bearing_status` to `mango`
and retires five hand-authored definitions. Two of those five carry values
somebody typed against real blocks, and this migration moves them rather than
stranding them:

## Size

Size is taken from `tree_age` first and from `003` only where no age was
recorded, because age is the better signal and `003` never asked about size
directly.

`tree_age` bands follow the size classes mango carries in the catalogue
(migration 0033: small under 2 m, medium 2-4 m, large over 4 m). A grafted
mango in Egypt is under 2 m for its first three or four years, reaches the
2-4 m band somewhere between years four and eight, and passes 4 m after
that:

    under 4 years   -> small
    4 to 8 years    -> medium
    over 8 years    -> large

`003` "Tree size" folded size and bearing into one three-option list, which
is why no rule could ask about size on its own. Where it is the only signal
it splits:

    01  Young non-productive   -> tree_size_class=small    bearing_status=not_bearing
    02  Young new-productive   -> tree_size_class=medium   bearing_status=bearing
    03  Mature productive      -> tree_size_class=large    bearing_status=bearing

Bearing always comes from `003`; only the size half is superseded by age.

Why age wins where both exist: on prod every block carrying `tree_age` reads
2 or 3 years, while 100 of them carry `003 = 02`. Mapping that straight to
`medium` would label a three-year-old planting as a 2-4 m canopy, and the
imagery agrees with the age rather than the label -- those blocks read NDVI
0.17-0.21 and SAVI 0.16-0.19, which are the guide's small-tree bands, not its
medium ones. Taking the label over the age would have put 100 of 108 blocks
below their expected range on the first sweep: a size error reported as a
crop problem.

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


# Age bands -> size class. (lower bound inclusive, upper bound exclusive,
# target option). Runs before the `003` fallback below.
_AGE_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 4, "small"),
    (4, 8, "medium"),
    (8, 200, "large"),
)

# (source code, source option, target code, target option)
_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("003", "01", "tree_size_class", "small"),
    ("003", "02", "tree_size_class", "medium"),
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

# Size from recorded tree age. Runs first, so the `003` fallback lands only on
# assignments with no age -- `_COPY` is ON CONFLICT DO NOTHING against the
# (block_crop_id, definition_id) unique constraint, which is what makes "age
# wins" work without a NOT EXISTS.
_COPY_AGE = sa.text(
    """
    INSERT INTO block_crop_attribute_values (
        block_crop_id, definition_id, definition_code, value_option
    )
    SELECT v.block_crop_id, target.id, target.code, :target_option
    FROM block_crop_attribute_values v
    JOIN public.crop_attribute_definitions src
      ON src.id = v.definition_id
     AND src.path = 'mango'
     AND src.code = 'tree_age'
    JOIN public.crop_attribute_definitions target
      ON target.path = 'mango'
     AND target.code = 'tree_size_class'
    WHERE v.deleted_at IS NULL
      AND v.value_numeric >= :low
      AND v.value_numeric < :high
    ON CONFLICT ON CONSTRAINT uq_block_crop_attribute_values_pair DO NOTHING
    """
)

# Reverses one mapping row exactly: a target value is removed only where the
# same assignment still carries the source value that would have produced it.
# Used for `bearing_status` and `establishment_method`, whose values map
# one-to-one from a `003` or `004` option.
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

# `tree_size_class` needs its own undo. It cannot use the pair match above:
# where age and `003` disagree the written class is the age's, so matching the
# `003` option against the stored value finds nothing and the row would
# survive a downgrade. Instead every size row on an assignment that carries
# one of the two sources is removed -- those assignments are exactly the ones
# this migration wrote to.
_UNDO_SIZE = sa.text(
    """
    DELETE FROM block_crop_attribute_values target_row
    USING public.crop_attribute_definitions target
    WHERE target.id = target_row.definition_id
      AND target.path = 'mango'
      AND target.code = 'tree_size_class'
      AND EXISTS (
          SELECT 1
          FROM block_crop_attribute_values source_row
          JOIN public.crop_attribute_definitions src ON src.id = source_row.definition_id
          WHERE source_row.block_crop_id = target_row.block_crop_id
            AND source_row.deleted_at IS NULL
            AND src.path = 'mango'
            AND src.code IN ('003', 'tree_age')
      )
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for low, high, target_option in _AGE_BANDS:
        bind.execute(_COPY_AGE, {"low": low, "high": high, "target_option": target_option})
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
    bind.execute(_UNDO_SIZE)
    for source_code, source_option, target_code, target_option in _MAP:
        if target_code == "tree_size_class":
            continue
        bind.execute(
            _UNDO,
            {
                "source_code": source_code,
                "source_option": source_option,
                "target_code": target_code,
                "target_option": target_option,
            },
        )
