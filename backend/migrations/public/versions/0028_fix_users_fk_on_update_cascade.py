"""Repair ON UPDATE CASCADE on the users back-references.

0023 tried to add ``ON UPDATE CASCADE`` to every FK that points at
``public.users(id)``, but it assumed SQLAlchemy's auto-naming
(``<table>_<column>_fkey``). Several of those FKs were created in 0003
with *explicit* names (e.g. ``fk_tenant_memberships_user_id_users``), so
0023's ``DROP CONSTRAINT IF EXISTS <auto-name>`` was a no-op and it then
ADDed a *second* FK under the auto-name. The result was two FKs on the
same column: the original explicit one (``ON DELETE`` only) plus 0023's
cascade one. On ``UPDATE users.id`` the original still RESTRICTs, so the
keycloak-subject rekey path fails with a FK violation.

This migration makes each user-referencing FK canonical: drop *every*
FK on that (table, column) that targets ``public.users``, then add one
constraint with ``ON UPDATE CASCADE`` and the intended ``ON DELETE``.
Driven by a catalog query so it's independent of the leftover names.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (referencing_table, column, on_delete) — the canonical FK we want.
_FKS: tuple[tuple[str, str, str], ...] = (
    ("tenant_memberships", "user_id", "CASCADE"),
    ("tenant_memberships", "invited_by", "SET NULL"),
    ("tenant_role_assignments", "granted_by", "SET NULL"),
    ("platform_role_assignments", "user_id", "CASCADE"),
    ("platform_role_assignments", "granted_by", "SET NULL"),
    ("farm_scopes", "granted_by", "SET NULL"),
    ("user_preferences", "user_id", "CASCADE"),
)


def _drop_all_user_fks(table: str, column: str) -> str:
    # Drop every FK on public.<table>.<column> that references public.users,
    # whatever it's named (handles both the 0003 explicit name and 0023's
    # auto-named duplicate). table/column come from the hardcoded _FKS tuple,
    # not user input.
    return f"""
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            JOIN pg_class ref ON ref.oid = con.confrelid
            WHERE ns.nspname = 'public'
              AND rel.relname = '{table}'
              AND ref.relname = 'users'
              AND con.contype = 'f'
              AND con.conkey = ARRAY[
                (SELECT attnum FROM pg_attribute
                  WHERE attrelid = rel.oid AND attname = '{column}')
              ]
          LOOP
            EXECUTE format('ALTER TABLE public.{table} DROP CONSTRAINT %I', r.conname);
          END LOOP;
        END $$;
    """


def upgrade() -> None:
    for table, column, on_delete in _FKS:
        op.execute(_drop_all_user_fks(table, column))
        op.execute(
            f"ALTER TABLE public.{table} "
            f'ADD CONSTRAINT "fk_{table}_{column}_users" FOREIGN KEY ({column}) '
            f"REFERENCES public.users(id) "
            f"ON UPDATE CASCADE ON DELETE {on_delete}"
        )


def downgrade() -> None:
    # Restore the pre-0028 shape: a single FK without ON UPDATE CASCADE
    # (matches 0003's intent; the 0023 duplicate is not recreated).
    for table, column, on_delete in _FKS:
        op.execute(_drop_all_user_fks(table, column))
        op.execute(
            f"ALTER TABLE public.{table} "
            f'ADD CONSTRAINT "fk_{table}_{column}_users" FOREIGN KEY ({column}) '
            f"REFERENCES public.users(id) "
            f"ON DELETE {on_delete}"
        )
