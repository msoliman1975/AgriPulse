"""Drop tenant.rule_overrides + tenant.tenant_rules (Stage 2 of rules sunset).

PR-F (the Stage 1 PR) disabled the rules-engine Beat sweep and shipped
the `ndvi_baseline_alert_v1` decision-tree seed that replaces the
platform `default_rules` rows 1:1. Trees now own all alert generation
(via `_open_alert_from_tree` in `recommendations.service`, writing
into `tenant.alerts` with `rule_code = 'tree:<tree_code>:<leaf_id>'`).

Stage 2 (this PR) drops the per-tenant rule tables:

  * `tenant_<id>.rule_overrides` — was per-tenant tweaks on platform
    rules. The new tenant-side knob is `tree_parameter_overrides`
    (0032), which is strictly typed against declared parameters and
    rejects shadow predicates that `rule_overrides` allowed.
  * `tenant_<id>.tenant_rules` — was wholly-authored tenant rules.
    The new authoring path is tenant-authored decision trees via the
    PR-D editor (`/settings/decision-trees/new`).

Drop preconditions (operator responsibility — NOT enforced here):

  1. Run `scripts/sunset-rules/audit_tenant_rules.py --schema
     tenant_<hex>` against every active tenant. Translate any
     non-trivial rows into either:
       - `tree_parameter_overrides` rows (for threshold tweaks), OR
       - tenant-authored decision-tree YAMLs (for structural rules).
  2. Run dev/staging on tree-as-alerts for at least one full Beat
     cycle to confirm no alerts that the legacy rules used to fire
     are now silent.

Once Stage 2 ships, the `alerts` module loses `engine.py` + `tasks.py`
+ the rule-related ORM/repo/service/router/schema slices; the
`Alert` model + lifecycle (acknowledge / resolve / snooze) stays.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `rule_overrides` first (no FKs into it). Indexes go with the table
    # in Postgres so we don't need explicit `drop_index` calls.
    op.drop_table("rule_overrides")
    op.drop_table("tenant_rules")


def downgrade() -> None:
    # Restoring the rule tables would also need re-seeding the
    # platform default_rules + re-registering the Celery beat task +
    # reverting the alerts module code. Downgrade here is structural
    # only — a true rollback of Stage 2 is a multi-file revert, not a
    # `alembic downgrade`.
    op.create_table(
        "tenant_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'warning'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "applies_to_crop_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rule_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("modified_conditions", postgresql.JSONB(), nullable=True),
        sa.Column("modified_actions", postgresql.JSONB(), nullable=True),
        sa.Column("modified_severity", sa.Text(), nullable=True),
        sa.Column(
            "is_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
