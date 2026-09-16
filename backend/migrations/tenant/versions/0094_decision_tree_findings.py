"""A tenant's own finding codes, for a tree the platform has not shipped.

The same shape as `public.decision_tree_findings` (public migration 0090),
in the tenant's schema. A tenant authoring its own folding tree needs a
code for something the platform catalogue does not carry, and waiting for
a platform release to get one would stop the tree being publishable at
all.

**The platform wins on a duplicate code.** The fold resolves the platform
table first and then the tenant table, and a tenant row whose code already
exists in `public` is never read — `resolve_findings` in
``app.modules.recommendations.findings`` is the one place that rule lives.
The row is kept rather than rejected so the admin screen can show it as
shadowed and the tenant can see why their clause is not the one appearing
on the card. A write-time rejection would also be wrong: the platform can
add a code tomorrow and shadow a tenant row that was legal when it was
written.

**No foreign key to `public`, by design and by rule.** There is nothing to
point at — a shadowed code is matched by string, in Python, at fold time.
A tenant schema must never hold a foreign key into `public` whatever the
temptation.

**Not in the purge manifest, and that is correct.** The manifest covers
tenant-schema tables that carry `tenant_id`, `farm_id` or `block_id` and
would orphan, plus public-schema residue. This table carries none of those
columns: the schema is the tenancy. A tenant purge drops the schema
wholesale with `DROP SCHEMA ... CASCADE` and takes it. `registry.py`
carries a note saying so.

Design: docs/proposals/unified-decision-tree-engine.md section 6.2.

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

# Kept in step with `app.modules.recommendations.status_codes.STATUS_CODES`
# and with public migration 0090's copy of the same list. A unit test pins
# all three to each other.
_STATUS_CODES = "'na', 'very_good', 'good', 'issue', 'alert'"


def upgrade() -> None:
    op.create_table(
        "decision_tree_findings",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("clause_en", sa.Text(), nullable=False),
        sa.Column("clause_ar", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("default_status", sa.Text(), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        # Every CHECK is named by its SUFFIX only. The metadata naming
        # convention is `ck_%(table_name)s_%(constraint_name)s`, so a full
        # name here would land in the database doubled.
        sa.CheckConstraint(f"default_status IN ({_STATUS_CODES})", name="default_status"),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_shape"),
        # A clause is joined with other clauses by the fold, using commas, so
        # it must not carry one of its own. Same three rules as the platform
        # table: a tenant clause is composed by exactly the same code.
        sa.CheckConstraint("clause_en NOT LIKE '%,%'", name="clause_en_no_comma"),
        sa.CheckConstraint("clause_ar NOT LIKE '%,%'", name="clause_ar_no_comma"),
        sa.CheckConstraint("clause_ar NOT LIKE '%،%'", name="clause_ar_no_arabic_comma"),
    )

    op.create_index(
        "ix_decision_tree_findings_active",
        "decision_tree_findings",
        ["code"],
        postgresql_where=sa.text("is_active"),
    )

    op.execute(
        "CREATE TRIGGER trg_decision_tree_findings_updated_at "
        "BEFORE UPDATE ON decision_tree_findings "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_decision_tree_findings_updated_at ON decision_tree_findings"
    )
    op.drop_index("ix_decision_tree_findings_active", table_name="decision_tree_findings")
    op.drop_table("decision_tree_findings")
