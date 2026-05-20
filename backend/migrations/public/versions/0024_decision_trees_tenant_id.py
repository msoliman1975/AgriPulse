"""decision_trees.tenant_id (PR-A): tenant-scope authoring.

PR 0015 created `public.decision_trees` as a platform-only catalog with
a global UNIQUE on `code`. PR-A makes the catalog shared: tenants can
author their own trees in the same table, scoped by a new `tenant_id`
column. NULL = platform-shipped (the YAML seed loader continues to own
those); non-NULL = tenant-authored via the API.

Code uniqueness becomes scoped via two partial unique indexes:
  * platform trees: UNIQUE (code)              WHERE tenant_id IS NULL
  * tenant trees:   UNIQUE (tenant_id, code)   WHERE tenant_id IS NOT NULL

App-level enforcement (in `DecisionTreesAuthorService.create_tree`)
additionally rejects tenant-authored codes that collide with platform
codes, so `code` remains an unambiguous lookup key for any tenant's
visibility scope. That check lives in code, not the DB, because the
"don't shadow a platform tree" rule applies only to creates from the
authoring API; the YAML seed loader is allowed to add platform rows
freely.

`UNIQUE NULLS NOT DISTINCT` is deliberately NOT used: that would
collide multiple distinct platform rows (all with `tenant_id IS NULL`),
which is the case we *want* to allow -- multiple platform trees with
different codes share a NULL `tenant_id`.

Existing rows: any `decision_trees` already in the catalog keep
`tenant_id = NULL` after this migration (i.e., become platform trees).
A dev tenant that previously authored a tree via POST `/decision-trees`
and wants it re-attributed needs a manual UPDATE; per
project_inflight_prs memory there are no such rows in dev today
(2026-05-19).

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="public",
    )

    # Replace the global UNIQUE on `code` with the two partial uniques
    # below. PR 0015 used inline `unique=True` on the column which lets
    # PG pick the constraint name; we look it up dynamically by column
    # rather than hard-coding a name that could differ across env history.
    op.execute(
        """
        DO $$
        DECLARE
            cname text;
        BEGIN
            SELECT conname INTO cname
            FROM pg_constraint
            WHERE conrelid = 'public.decision_trees'::regclass
              AND contype = 'u'
              AND conkey = (
                  SELECT array_agg(attnum)
                  FROM pg_attribute
                  WHERE attrelid = 'public.decision_trees'::regclass
                    AND attname = 'code'
              );
            IF cname IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE public.decision_trees DROP CONSTRAINT %I',
                    cname
                );
            END IF;
        END
        $$;
        """
    )

    op.create_index(
        "uq_decision_trees_platform_code",
        "decision_trees",
        ["code"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_decision_trees_tenant_code",
        "decision_trees",
        ["tenant_id", "code"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL AND deleted_at IS NULL"),
    )

    # Speeds up the sweep predicate (`tenant_id = :ctx`). The platform
    # leg (`tenant_id IS NULL`) is already served by
    # `uq_decision_trees_platform_code`.
    op.create_index(
        "ix_decision_trees_tenant_id",
        "decision_trees",
        ["tenant_id"],
        schema="public",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_trees_tenant_id",
        table_name="decision_trees",
        schema="public",
    )
    op.drop_index(
        "uq_decision_trees_tenant_code",
        table_name="decision_trees",
        schema="public",
    )
    op.drop_index(
        "uq_decision_trees_platform_code",
        table_name="decision_trees",
        schema="public",
    )
    op.create_unique_constraint(
        "decision_trees_code_key",
        "decision_trees",
        ["code"],
        schema="public",
    )
    op.drop_column("decision_trees", "tenant_id", schema="public")
