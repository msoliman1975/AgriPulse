"""Folding execution: the finding set on a card, on a trace, and per-farm parameters.

Three changes, one file, because they are the storage half of one behaviour:
a folding decision tree collects *findings* as it walks and folds them into
one card at ``stop``
(``docs/proposals/unified-decision-tree-engine.md`` sections 5.6, 6.4, 6.6,
6.7).

**1. ``recommendations.finding_set``.** The sorted finding codes the card was
folded from. It is the card's identity and it is read twice: the Action Center
groups cells on it, and the next evaluation compares the stored set against the
new one to decide whether the open card still describes what the tree found.
Not null, default ``[]``, so every row written before folding existed reads as
"no findings" rather than as null, and the supersede comparison never has to
special-case a missing value.

**2. Three columns on ``decision_tree_eval_traces``.** ``finding_set``,
``matched_rule`` and ``registered_by``. Unlike ``node_path`` and
``resolved_values``, whose grain is deliberately uneven (0062: a ``clear`` row
keeps the path and drops the values), these three are written on every row
whatever the status. They are short — a handful of codes, one rule id, one code
to node-id map — and they answer the first question anyone asks of a folding
run: which findings did this walk hold at the end, and where did the text come
from.

``registered_by`` is ``{code: [node_id, ...]}``. A repeated register of one
code is one finding, not two, so without this the trace cannot show that three
separate checks agreed.

**3. ``tree_parameter_overrides.farm_id``.** Resolution gains a third layer:
the tree's declared default, then the tenant row, then the farm row.

The design calls the new key "the primary key becomes
``(tree_id, param_name, farm_id)``, with a partial unique index for the
``farm_id IS NULL`` row". A primary key cannot hold a nullable column, so that
key is expressed here as the two partial unique indexes it actually means:

    (tree_id, param_name, farm_id) WHERE farm_id IS NOT NULL   -- one per farm
    (tree_id, param_name)          WHERE farm_id IS NULL       -- one tenant row

Both halves are unique, which is the property the upserts need, and neither can
be a primary key on its own.

**Dropping the old primary key by its real name.** ``op.drop_constraint``
doubles a name the same way ``create_check_constraint`` does, and this
constraint was named explicitly in 0032 rather than by convention. Rather than
guess which spelling is on disk, the drop below reads the name out of
``pg_constraint`` and executes it. That is correct whatever the name turns out
to be, in a schema created today and in one created in 2026-05.

**Purge.** ``farm_id`` is an ownership column, so the table joins the farm
manifest in ``app/shared/purge/registry.py``. Purging a farm deletes that
farm's override rows and leaves the tenant-level row (``farm_id IS NULL``)
standing, which is right: it belongs to the tenant, not to the farm.

Revision ID: 0094
Revises: 0093
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0094"
down_revision: str | Sequence[str] | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DROP_PK_BY_REAL_NAME = """
DO $$
DECLARE
    pk_name text;
BEGIN
    SELECT conname INTO pk_name
      FROM pg_constraint
     WHERE conrelid = 'tree_parameter_overrides'::regclass
       AND contype = 'p';
    IF pk_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE tree_parameter_overrides DROP CONSTRAINT %I', pk_name
        );
    END IF;
END $$;
"""


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column(
            "finding_set",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.add_column(
        "decision_tree_eval_traces",
        sa.Column(
            "finding_set",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "decision_tree_eval_traces",
        sa.Column("matched_rule", sa.Text(), nullable=True),
    )
    op.add_column(
        "decision_tree_eval_traces",
        sa.Column(
            "registered_by",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column(
        "tree_parameter_overrides",
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(_DROP_PK_BY_REAL_NAME)
    op.create_index(
        "uq_tree_parameter_overrides_tenant_row",
        "tree_parameter_overrides",
        ["tree_id", "param_name"],
        unique=True,
        postgresql_where=sa.text("farm_id IS NULL"),
    )
    op.create_index(
        "uq_tree_parameter_overrides_farm_row",
        "tree_parameter_overrides",
        ["tree_id", "param_name", "farm_id"],
        unique=True,
        postgresql_where=sa.text("farm_id IS NOT NULL"),
    )
    # The sweep reads every farm's rows for a set of trees in one statement.
    op.create_index(
        "ix_tree_parameter_overrides_farm",
        "tree_parameter_overrides",
        ["farm_id"],
        postgresql_where=sa.text("farm_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tree_parameter_overrides_farm", table_name="tree_parameter_overrides")
    op.drop_index("uq_tree_parameter_overrides_farm_row", table_name="tree_parameter_overrides")
    op.drop_index("uq_tree_parameter_overrides_tenant_row", table_name="tree_parameter_overrides")
    # A farm row cannot survive the old key, which admits one row per
    # (tree, param). They are deleted rather than merged: a tenant-level value
    # already exists for every parameter, so the farm rows are the additions.
    op.execute("DELETE FROM tree_parameter_overrides WHERE farm_id IS NOT NULL")
    op.drop_column("tree_parameter_overrides", "farm_id")
    op.create_primary_key(
        "pk_tree_parameter_overrides",
        "tree_parameter_overrides",
        ["tree_id", "param_name"],
    )

    op.drop_column("decision_tree_eval_traces", "registered_by")
    op.drop_column("decision_tree_eval_traces", "matched_rule")
    op.drop_column("decision_tree_eval_traces", "finding_set")
    op.drop_column("recommendations", "finding_set")
