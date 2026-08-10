"""Signal catalog gains a platform tier — the public half (T1).

Signal definitions and templates have always been tenant-only
(``tenant_<id>.signal_definitions``), authored per tenant at
``/config/signals/:farmId``. Unlike ``decision_trees`` and ``crops`` there was
no platform tier at all, so a curated form set could never be published once
and read by everybody — every tenant had to rebuild it, and an improvement
reached nobody.

This migration creates the destination tables only. It is deliberately inert:
nothing writes to them until tenant migration ``0063`` copies each tenant's
rows up and drops the tenant-schema originals. Splitting it this way is
required, not stylistic — the ArgoCD PreSync hook runs
``alembic -n public upgrade head`` before ``scripts.migrate_tenants``
(``infra/helm/api/templates/migration-job.yaml``), so the destination is
guaranteed to exist before any tenant tries to INSERT into it.

Scope discriminator, mirroring ``public.decision_trees``::

    tenant_id IS NULL      -> platform-curated  (authored at /platform/signals)
    tenant_id IS NOT NULL  -> tenant-authored   (unchanged behaviour)

Reads resolve both tiers with ``WHERE tenant_id IS NULL OR tenant_id = :tid``,
and a tenant row **shadows** a platform row sharing its ``code`` — see the
implementation plan, docs/proposals/signals-platform-tier-implementation.md.

Column set is copied verbatim from the tenant tables as they stand after
tenant migrations 0017 (original), 0029 (aggregation + templates) and 0035
(``count``/``sum`` aggregation), plus the new ``tenant_id``. Divergence here
would break the 0063 copy-up, which preserves primary keys so the
``signal_observations`` hypertable — which references definitions with no FK —
keeps resolving untouched.

Two things differ from the tenant originals, both deliberate:

* ``uq_*_code_active`` becomes two partial unique indexes instead of one,
  partitioned by scope. Both keep the original ``deleted_at IS NULL``
  predicate, so a soft-deleted code still frees its name for reuse.
* ``set_updated_at()`` triggers are attached, which the tenant tables never
  had. Every other public catalog table maintains ``updated_at`` this way. The
  trigger is BEFORE UPDATE only, so the 0063 copy-up (an INSERT) still
  preserves each row's original timestamps.

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in sync with tenant migrations 0017 / 0029 / 0035. If either side
# gains a value, both must move together or the 0063 copy-up rejects rows.
_VALUE_KINDS = "'numeric', 'categorical', 'event', 'boolean', 'geopoint'"
_AGGREGATIONS = "'latest', 'mean', 'median', 'max', 'min', 'count', 'sum'"


def upgrade() -> None:
    # ---- signal_definitions ------------------------------------------------
    op.create_table(
        "signal_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # NULL = platform-curated; non-NULL = tenant-authored. No FK to
        # public.tenants: purge deletes tenant rows via the ownership manifest
        # (shared/purge/registry.py), exactly as public.decision_trees does,
        # and a CASCADE here would let a tenant delete take the catalog with it.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_kind", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("categorical_values", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("value_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("value_max", sa.Numeric(12, 4), nullable=True),
        # Gates whether the capture UI offers a camera at all. Unset it and the
        # feature silently never appears — no error, just a missing control.
        sa.Column(
            "attachment_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        # Read by the recommendations engine via signals/snapshot.py to collapse
        # observations to one block-level value per signal.
        sa.Column("aggregation", sa.Text(), nullable=False, server_default=sa.text("'latest'")),
        sa.Column("aggregation_window_days", sa.Integer(), nullable=True),
        # Full TimestampedMixin column set (data_model § 1.4). Omitting
        # created_by / updated_by / deleted_at makes every ORM SELECT fail with
        # UndefinedColumn.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"value_kind IN ({_VALUE_KINDS})", name="value_kind"),
        sa.CheckConstraint(f"aggregation IN ({_AGGREGATIONS})", name="aggregation"),
        sa.CheckConstraint(
            "aggregation_window_days IS NULL OR aggregation_window_days > 0",
            name="aggregation_window_positive",
        ),
        schema="public",
    )

    # Code uniqueness partitioned by scope — the decision_trees pattern
    # (public migration 0024). One platform row per code, and one row per code
    # per tenant, so a tenant may define `canopy_vigour` even though the
    # platform ships one. Both keep the tenant tables' `deleted_at IS NULL`
    # predicate so soft-deleting a definition frees its code for reuse.
    op.create_index(
        "uq_signal_definitions_platform_code",
        "signal_definitions",
        ["code"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("tenant_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_signal_definitions_tenant_code",
        "signal_definitions",
        ["tenant_id", "code"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("tenant_id IS NOT NULL AND deleted_at IS NULL"),
    )
    # The two-tier read: `WHERE tenant_id IS NULL OR tenant_id = :tid`.
    op.create_index(
        "ix_signal_definitions_tenant",
        "signal_definitions",
        ["tenant_id"],
        schema="public",
    )

    # ---- signal_templates --------------------------------------------------
    op.create_table(
        "signal_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_index(
        "uq_signal_templates_platform_code",
        "signal_templates",
        ["code"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("tenant_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_signal_templates_tenant_code",
        "signal_templates",
        ["tenant_id", "code"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("tenant_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_signal_templates_tenant",
        "signal_templates",
        ["tenant_id"],
        schema="public",
    )

    # ---- signal_template_definitions --------------------------------------
    # Pure junction: no tenant_id of its own, so it never appears in the purge
    # ownership sweep. It is owned transitively through its template, and
    # CASCADE handles the delete.
    op.create_table(
        "signal_template_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.signal_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.signal_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Display order within the template's entry form, 0-indexed.
        sa.Column("position", sa.Integer(), nullable=False),
        # UX-layer hint only — the underlying per-definition observation is
        # always nullable.
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.UniqueConstraint("template_id", "signal_definition_id", name="uq_template_definition"),
        sa.UniqueConstraint("template_id", "position", name="uq_template_position"),
        schema="public",
    )

    # ---- updated_at maintenance -------------------------------------------
    # Every public catalog table gets this; the tenant originals never had it.
    # BEFORE UPDATE only, so the 0063 copy-up INSERT preserves original stamps.
    for table in ("signal_definitions", "signal_templates"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at "
            f"BEFORE UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
        )


def downgrade() -> None:
    # Safe only while these tables are still empty — i.e. before tenant
    # migration 0063 has copied anything up. Once platform rows exist they have
    # no tenant schema to fall back to, and tenant observations reference their
    # ids; from that point roll forward instead.
    for table in ("signal_definitions", "signal_templates"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON public.{table}")

    op.drop_table("signal_template_definitions", schema="public")

    op.drop_index("ix_signal_templates_tenant", table_name="signal_templates", schema="public")
    op.drop_index("uq_signal_templates_tenant_code", table_name="signal_templates", schema="public")
    op.drop_index(
        "uq_signal_templates_platform_code", table_name="signal_templates", schema="public"
    )
    op.drop_table("signal_templates", schema="public")

    op.drop_index("ix_signal_definitions_tenant", table_name="signal_definitions", schema="public")
    op.drop_index(
        "uq_signal_definitions_tenant_code", table_name="signal_definitions", schema="public"
    )
    op.drop_index(
        "uq_signal_definitions_platform_code", table_name="signal_definitions", schema="public"
    )
    op.drop_table("signal_definitions", schema="public")
