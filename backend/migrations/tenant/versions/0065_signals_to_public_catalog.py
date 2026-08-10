"""Signal catalog gains a platform tier — the tenant half (T2).

Public migration ``0052`` created ``public.signal_definitions`` /
``signal_templates`` / ``signal_template_definitions``. This migration moves
each tenant's rows up into them and drops the tenant-schema originals, so the
catalog has a single home with a scope discriminator::

    tenant_id IS NULL      -> platform-curated
    tenant_id IS NOT NULL  -> tenant-authored (these rows)

Runs once per schema via ``scripts.migrate_tenants``, which the ArgoCD PreSync
hook invokes *after* ``alembic -n public upgrade head`` — so the destination
tables are guaranteed to exist (``infra/helm/api/templates/migration-job.yaml``).

**Primary keys are preserved.** ``signal_observations`` references
``signal_definition_id`` with no FK at all (a deliberate logical reference —
see tenant migration 0017), so keeping ids identical means the hypertable and
every historical observation keep resolving without being touched.
``signal_assignments`` now joins it: its FK is dropped rather than repointed at
``public``, because a tenant -> public FK forces ``DROP SCHEMA tenant_x
CASCADE`` to take an ACCESS EXCLUSIVE lock on the shared catalog and serialises
tenant lifecycle platform-wide. 0017's logical-reference choice was right; this
migration follows it instead of inventing the schema's only tenant -> public FK.

Ordering matters and is not arbitrary:

1. copy definitions, then templates, then the junction (FK order);
2. drop the tenant junction table — it carries FKs into both tenant tables;
3. drop ``signal_assignments``' FK, leaving a logical reference;
4. only then drop the two tenant catalog tables.

Idempotency: Postgres gives us transactional DDL, so a failure rolls the whole
tenant back and Alembic's per-tenant version table means the next run retries
cleanly. ``ON CONFLICT (id) DO NOTHING`` is belt-and-braces on top of that —
``migrate_tenants`` walks the fleet with ``backoffLimit: 1``, so a partially
migrated fleet is a state we must be able to re-enter.

Constraint names are resolved from ``pg_constraint`` rather than hardcoded.
This is not defensive habit: the real junction FK in a live schema is
``fk_signal_template_definitions_signal_definition_id_sig_9598`` — Alembic's
convention overflowed Postgres' 63-character identifier limit and got truncated
with a hash suffix. Any hardcoded name would be wrong on some schemas.

Downgrade recreates the tenant tables and copies this tenant's rows back.
**It cannot restore platform rows** (``tenant_id IS NULL``) — they have no
tenant schema to return to. Downgrade is therefore only safe before the
platform catalog is seeded (T6); after that, roll forward.

Revision ID: 0063
Revises: 0062
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Resolve this schema's tenant the way tenant migration 0046 does:
# search_path puts the tenant schema first, so current_schema() is it, and
# schema names are the tenant uuid with dashes stripped.
_TENANT_ID_SQL = """
    (SELECT t.id FROM public.tenants t
      WHERE replace(t.id::text, '-', '') = replace(current_schema(), 'tenant_', ''))
"""

_DEFINITION_COLUMNS = """
    id, code, name, description, value_kind, unit, categorical_values,
    value_min, value_max, attachment_allowed, is_active,
    aggregation, aggregation_window_days,
    created_at, created_by, updated_at, updated_by, deleted_at
"""

_TEMPLATE_COLUMNS = """
    id, code, name, description, is_active,
    created_at, created_by, updated_at, updated_by, deleted_at
"""


def _guard_tenant_resolvable() -> None:
    """Fail loudly if rows would be copied up with a NULL ``tenant_id``.

    Without this the tenant_id subquery yields NULL and every one of the
    tenant's definitions is copied up as a **platform** row — instantly visible
    to every other tenant on the installation. A hard failure is enormously
    preferable to that.

    The guard is conditional on there actually being rows to move. A tenant
    provisioned *after* this migration ships replays the whole chain inside its
    creation transaction, and at that moment no committed ``public.tenants`` row
    matches the schema yet — but its catalog tables are also empty, so there is
    nothing that could be mis-scoped. Guarding unconditionally would make this
    migration break tenant creation itself, which is precisely what the purge
    registry's guard test caught.
    """
    op.execute(
        f"""
        DO $$
        DECLARE
          pending bigint;
        BEGIN
          SELECT (SELECT count(*) FROM signal_definitions)
               + (SELECT count(*) FROM signal_templates)
            INTO pending;

          IF pending > 0 AND {_TENANT_ID_SQL} IS NULL THEN
            RAISE EXCEPTION
              'signals catalog move: no public.tenants row matches schema %, '
              'but % catalog row(s) are waiting to move; refusing to copy them '
              'up as platform-scoped',
              current_schema(), pending;
          END IF;
        END $$;
        """  # noqa: S608 - module constants only; no caller input reaches this
    )


def _fk_name(table: str, column: str) -> str:
    """Read a foreign key's real name out of the catalog.

    Alembic's naming convention can overflow Postgres' 63-char identifier
    limit and get truncated with a hash suffix, so names differ between
    tables and cannot be reconstructed.
    """
    bind = op.get_bind()
    return bind.execute(
        sa.text(
            """
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.contype = 'f'
               AND c.conrelid = (current_schema() || '.' || :tbl)::regclass
               AND a.attname = :col
             LIMIT 1
            """
        ),
        {"tbl": table, "col": column},
    ).scalar_one()


def upgrade() -> None:
    _guard_tenant_resolvable()

    # ---- 1. copy up, preserving ids ---------------------------------------
    op.execute(
        f"""
        INSERT INTO public.signal_definitions (tenant_id, {_DEFINITION_COLUMNS})
        SELECT {_TENANT_ID_SQL}, {_DEFINITION_COLUMNS}
          FROM signal_definitions
        ON CONFLICT (id) DO NOTHING
        """  # noqa: S608 - module constants only; no caller input reaches this
    )
    op.execute(
        f"""
        INSERT INTO public.signal_templates (tenant_id, {_TEMPLATE_COLUMNS})
        SELECT {_TENANT_ID_SQL}, {_TEMPLATE_COLUMNS}
          FROM signal_templates
        ON CONFLICT (id) DO NOTHING
        """  # noqa: S608 - module constants only; no caller input reaches this
    )
    op.execute(
        """
        INSERT INTO public.signal_template_definitions
            (id, template_id, signal_definition_id, position, is_required)
        SELECT id, template_id, signal_definition_id, position, is_required
          FROM signal_template_definitions
        ON CONFLICT (id) DO NOTHING
        """
    )

    # ---- 2. drop the tenant junction (holds FKs into both tenant tables) ---
    op.execute("DROP TABLE IF EXISTS signal_template_definitions")

    # ---- 3. repoint signal_assignments at the public catalog --------------
    # Drop the tenant-local FK and deliberately do NOT replace it with a
    # cross-schema one. A tenant -> public FK puts public.signal_definitions in
    # every tenant schema's dependency graph, so `DROP SCHEMA tenant_x CASCADE`
    # has to take an ACCESS EXCLUSIVE lock on it to drop the constraint. That
    # conflicts with the ROW EXCLUSIVE held by any concurrent tenant creation or
    # signal edit, which serialises tenant lifecycle platform-wide and hangs
    # outright behind one idle-in-transaction session.
    #
    # The FK bought nothing anyway: definitions are soft-deleted, so its
    # ON DELETE CASCADE could never fire, and tenant purge deletes
    # signal_assignments through its own manifest entry.
    #
    # The column keeps its index (created with the table), so lookups by
    # definition are unaffected. Integrity is the service layer's job — see
    # SignalAssignment in app/modules/signals/models.py.
    fk = _fk_name("signal_assignments", "signal_definition_id")
    op.drop_constraint(fk, "signal_assignments", type_="foreignkey")

    # ---- 4. drop the tenant catalog tables ---------------------------------
    # IF EXISTS because a tenant provisioned after this migration ships replays
    # the whole chain from 0001 — creating these at 0017/0029 and dropping them
    # again here — and the chain must tolerate being squashed later.
    op.execute("DROP TABLE IF EXISTS signal_templates")
    op.execute("DROP TABLE IF EXISTS signal_definitions")


def downgrade() -> None:
    # ---- 1. recreate the tenant tables (DDL as of 0017 + 0029 + 0035) ------
    op.create_table(
        "signal_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_kind", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("categorical_values", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("value_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("value_max", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "attachment_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("aggregation", sa.Text(), nullable=False, server_default=sa.text("'latest'")),
        sa.Column("aggregation_window_days", sa.Integer(), nullable=True),
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
    op.create_check_constraint(
        "value_kind",
        "signal_definitions",
        "value_kind IN ('numeric','categorical','event','boolean','geopoint')",
    )
    op.create_check_constraint(
        "aggregation",
        "signal_definitions",
        "aggregation IN ('latest','mean','median','max','min','count','sum')",
    )
    op.create_check_constraint(
        "aggregation_window_positive",
        "signal_definitions",
        "aggregation_window_days IS NULL OR aggregation_window_days > 0",
    )
    op.create_index(
        "uq_signal_definitions_code_active",
        "signal_definitions",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "signal_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
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
    op.create_index(
        "uq_signal_templates_code_active",
        "signal_templates",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

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
            sa.ForeignKey("signal_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signal_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    op.create_unique_constraint(
        "uq_signal_template_definitions_template_definition",
        "signal_template_definitions",
        ["template_id", "signal_definition_id"],
    )
    op.create_unique_constraint(
        "uq_signal_template_definitions_template_position",
        "signal_template_definitions",
        ["template_id", "position"],
    )

    # ---- 2. copy this tenant's rows back -----------------------------------
    # Platform rows (tenant_id IS NULL) are intentionally NOT restored: they
    # belong to no tenant schema. Any observation referencing one is orphaned
    # by this downgrade, which is why it is only safe before T6 seeding.
    op.execute(
        f"""
        INSERT INTO signal_definitions ({_DEFINITION_COLUMNS})
        SELECT {_DEFINITION_COLUMNS}
          FROM public.signal_definitions
         WHERE tenant_id = {_TENANT_ID_SQL}
        """  # noqa: S608 - module constants only; no caller input reaches this
    )
    op.execute(
        f"""
        INSERT INTO signal_templates ({_TEMPLATE_COLUMNS})
        SELECT {_TEMPLATE_COLUMNS}
          FROM public.signal_templates
         WHERE tenant_id = {_TENANT_ID_SQL}
        """  # noqa: S608 - module constants only; no caller input reaches this
    )
    op.execute(
        f"""
        INSERT INTO signal_template_definitions
            (id, template_id, signal_definition_id, position, is_required)
        SELECT td.id, td.template_id, td.signal_definition_id, td.position, td.is_required
          FROM public.signal_template_definitions td
          JOIN public.signal_templates t ON t.id = td.template_id
         WHERE t.tenant_id = {_TENANT_ID_SQL}
        """  # noqa: S608 - module constants only; no caller input reaches this
    )

    # ---- 3. repoint signal_assignments back at the tenant table ------------
    # `upgrade` leaves the column with no FK at all, so there is nothing to drop
    # here — `_fk_name` would raise on an empty result. Re-adding the
    # tenant-local FK is safe in this direction: it references a table inside
    # the same schema, which is what made the original shape unproblematic.
    op.create_foreign_key(
        "fk_signal_assignments_signal_definition_id_signal_definitions",
        "signal_assignments",
        "signal_definitions",
        ["signal_definition_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---- 4. remove this tenant's rows from the public catalog --------------
    # S608 suppressed below: module constants only, no caller input interpolates.
    op.execute(
        f"DELETE FROM public.signal_templates WHERE tenant_id = {_TENANT_ID_SQL}"  # noqa: S608
    )
    op.execute(
        f"DELETE FROM public.signal_definitions WHERE tenant_id = {_TENANT_ID_SQL}"  # noqa: S608
    )
