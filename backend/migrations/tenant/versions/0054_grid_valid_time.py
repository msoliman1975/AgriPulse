"""Grid configs get valid time, so a rezone stops orphaning history.

``grid_configs.retired_at`` is **transaction time** — the audit record of
when an operator changed their mind. Every config-joined read path filters
``retired_at IS NULL``, which silently overloads that column with a second
meaning it cannot carry: *which scene times this geometry governs*. The
result is the §2.2 defect — rezone a block and its entire observation
history becomes unreachable (kept, compressed, charged for, readable by
nothing), while the two read paths that don't join ``grid_configs`` keep
returning scene times that resolve to zero cells.

This migration adds **valid time** alongside transaction time rather than
reinterpreting ``retired_at``. Keeping both is the point: "when did we
change this" and "what period does it describe" are different questions,
and conflating them is the original bug.

Columns
-------
``effective_from`` / ``effective_to``
    The scene-time range this geometry governs. ``effective_to IS NULL``
    means open-ended — "and everything after". Reads become a containment
    test against the observation's ``time`` instead of a retired_at check.

``superseded_at``
    Governs *nothing*. Set when a config has been fully replaced over its
    whole range by a rezone that recomputed history (§A4 step 2). Its
    aggregate rows are still physically present until the cleanup task
    drops them, so it must be excluded from the non-overlap guard —
    otherwise the replacement config, which claims the same range, could
    never be inserted.

Backfill is chosen so this migration cannot lose readable data:

* **active** configs (``retired_at IS NULL``) get ``[-infinity, NULL)`` —
  "this geometry governs all of history", which is exactly today's
  de-facto behaviour. Nothing changes for them.
* **retired** configs get ``effective_to = retired_at``, which makes their
  aggregates readable again for their own period. Retired configs are
  currently invisible to every read path, so this can only *add* data
  back — there is no state where a row becomes less visible than before.

Requires ``btree_gist`` for the exclusion constraint (UUID equality in a
GiST index). In this deployment it is already present as a side effect of
pgstac's bootstrap (public migration 0007), but relying on a third-party
bootstrap for our own constraint is a trap for any environment that skips
pgstac — so it is created explicitly and idempotently here.

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # btree_gist supplies the GiST operator class for `uuid WITH =`, which
    # the exclusion constraint below needs alongside the range's `&&`.
    # IF NOT EXISTS keeps this a catalog lookup (no AccessExclusiveLock on
    # pg_extension) wherever pgstac has already installed it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.add_column(
        "grid_configs",
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("'-infinity'::timestamptz"),
        ),
    )
    op.add_column(
        "grid_configs",
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "grid_configs",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Retired configs describe the period that ended when they were
    # retired. Active configs keep the open-ended default from the column
    # definition, so they need no UPDATE.
    op.execute(
        """
        UPDATE grid_configs
           SET effective_to = retired_at
         WHERE retired_at IS NOT NULL
           AND effective_to IS NULL
        """
    )

    # A range must not end before it starts. `-infinity` makes the lower
    # bound always comparable, so this is a genuine data guard rather than
    # a NULL-handling formality.
    # Named by its bare suffix, not the full `ck_grid_configs_...`. The
    # metadata naming convention is `ck_%(table_name)s_%(constraint_name)s`,
    # so passing a already-prefixed name renders it twice — this table
    # already carries `ck_grid_configs_ck_grid_configs_cell_size_positive`
    # from exactly that mistake. Create and drop both apply the convention,
    # so the two stay symmetric either way; this just spells it correctly.
    op.create_check_constraint(
        "effective_range",
        "grid_configs",
        "effective_to IS NULL OR effective_to > effective_from",
    )

    # The real invariant: at most one *governing* geometry per
    # (block, product) for any given scene time. The old partial unique
    # index only ever said "one current config", which is a weaker claim
    # and is what let history become ambiguous.
    #
    # Superseded configs are excluded — they govern nothing and are
    # awaiting row cleanup, so leaving them in would block the very
    # replacement that superseded them.
    op.execute(
        """
        ALTER TABLE grid_configs
          ADD CONSTRAINT ex_grid_configs_no_overlap
          EXCLUDE USING gist (
            block_id   WITH =,
            product_id WITH =,
            tstzrange(effective_from, effective_to) WITH &&
          ) WHERE (deleted_at IS NULL AND superseded_at IS NULL)
        """
    )

    # Supports the cleanup task's scan for rows to drop.
    op.create_index(
        "ix_grid_configs_superseded_at",
        "grid_configs",
        ["superseded_at"],
        postgresql_where=sa.text("superseded_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_grid_configs_superseded_at", table_name="grid_configs")
    op.execute("ALTER TABLE grid_configs DROP CONSTRAINT ex_grid_configs_no_overlap")
    # Bare suffix again — the convention re-renders it to the full name.
    op.drop_constraint("effective_range", "grid_configs", type_="check")
    op.drop_column("grid_configs", "superseded_at")
    op.drop_column("grid_configs", "effective_to")
    op.drop_column("grid_configs", "effective_from")
    # btree_gist is intentionally left installed — dropping an extension
    # cascades into anything else using it (pgstac does), and the rest of
    # this codebase treats extensions as create-only for that reason.
