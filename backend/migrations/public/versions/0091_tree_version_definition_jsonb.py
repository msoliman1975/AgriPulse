"""A tree version's definition, stored as JSON instead of YAML text.

Part 4 of the unified decision tree engine. The beta designer produces a
graph object and ``folding_compiler.compile_folding_tree`` takes a Python
dictionary. Between them, today, sits a YAML string: `tree_yaml` is
``Text NOT NULL`` and the authoring API takes ``tree_yaml: str``. So the
designer would have to serialise a dictionary to YAML text for the API to
parse it straight back.

That round trip is not free. Writing the merged mango tree out as YAML and
reading it back is what turned three switch nodes into unusable ones: PyYAML
reads an unquoted ``on:`` key as the boolean ``True`` (YAML 1.1), so
``switch.on`` arrived as ``switch[True]`` and the compiler reported "a switch
with nothing to switch on" for a switch that plainly had one. A JSON object
has one kind of key and cannot do that. It is also one fewer place Arabic
text can be re-encoded on the way through.

So this migration gives a version row a second, structured body:

  * ``tree_yaml`` becomes nullable. Every existing row keeps its text
    untouched — nothing is converted, and the old engine keeps reading it.
  * ``definition`` JSONB is added, null on every existing row.
  * A CHECK says exactly one of the two is not null, so a version row is
    never both and never neither. That is what lets every reader decide
    which engine a version belongs to from the row alone.

`tree_compiled` and `compiled_hash` are unchanged and are written for both
shapes. The compiled body already carries ``shape: 'folding'`` for a beta
tree (``folding_compiler.compile_folding_tree``), so the sweep can tell the
two apart without reading either source body.

Design: docs/proposals/unified-decision-tree-engine.md section 6.5.

Revision ID: 0091
Revises: 0090
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BODY_CHECK = "ck_decision_tree_versions_one_body"


def upgrade() -> None:
    op.add_column(
        "decision_tree_versions",
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="public",
    )
    op.alter_column(
        "decision_tree_versions",
        "tree_yaml",
        existing_type=sa.Text(),
        nullable=True,
        schema="public",
    )
    # Exactly one body. `num_nonnulls` is the shortest honest spelling of
    # "one and only one" and reads the same in psql as it does here.
    op.create_check_constraint(
        _BODY_CHECK,
        "decision_tree_versions",
        "num_nonnulls(tree_yaml, definition) = 1",
        schema="public",
    )


def downgrade() -> None:
    # Dropped by raw SQL with IF EXISTS rather than `op.drop_constraint`.
    # The constraint's real name has been the source of enough failed
    # downgrades in this repository that naming it once, here, and letting
    # Postgres shrug if it is already gone is worth the two extra lines.
    op.execute(f"ALTER TABLE public.decision_tree_versions DROP CONSTRAINT IF EXISTS {_BODY_CHECK}")
    # A beta row has no YAML at all, so it cannot survive the column going
    # back to NOT NULL. Downgrading means abandoning the beta shape, and
    # dropping those rows is the only way the old constraint can hold.
    op.execute("DELETE FROM public.decision_tree_versions WHERE tree_yaml IS NULL")
    op.alter_column(
        "decision_tree_versions",
        "tree_yaml",
        existing_type=sa.Text(),
        nullable=False,
        schema="public",
    )
    op.drop_column("decision_tree_versions", "definition", schema="public")
