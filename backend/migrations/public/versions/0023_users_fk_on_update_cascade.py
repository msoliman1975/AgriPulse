"""users FK references gain ON UPDATE CASCADE.

Background: every public table that points at `public.users.id` (memberships,
roles, preferences, audit refs) had a plain FK with no ON UPDATE clause.
The auth middleware uses the JWT `sub` claim as `public.users.id`, but
Keycloak users can be recreated (re-issuing a new `sub` for the same
email) — when that happens, the iam sync handler needs to re-key the
existing user row so all downstream membership / preference / audit rows
follow it without losing data.

Without ON UPDATE CASCADE, the rekey would either need a manual
multi-statement migration of every referencing row or would orphan
tenant_memberships. With ON UPDATE CASCADE, a single
`UPDATE public.users SET id = <new sub> WHERE email = ...` carries the
seven dependent FK columns with it automatically.

ON DELETE behavior is preserved per-FK (some are CASCADE, some
SET NULL, some were left default) — this migration only adds the
ON UPDATE side.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (referencing_table, column, fk_constraint_name, on_delete_clause)
# The constraint names follow SQLAlchemy's auto-naming
# (<table>_<column>_fkey). ON DELETE wording is matched to the original
# DDL so this migration only changes the ON UPDATE side.
_FKS: tuple[tuple[str, str, str, str], ...] = (
    ("tenant_memberships", "user_id", "tenant_memberships_user_id_fkey", "CASCADE"),
    ("tenant_memberships", "invited_by", "tenant_memberships_invited_by_fkey", "SET NULL"),
    (
        "tenant_role_assignments",
        "granted_by",
        "tenant_role_assignments_granted_by_fkey",
        "SET NULL",
    ),
    ("platform_role_assignments", "user_id", "platform_role_assignments_user_id_fkey", "CASCADE"),
    (
        "platform_role_assignments",
        "granted_by",
        "platform_role_assignments_granted_by_fkey",
        "SET NULL",
    ),
    ("farm_scopes", "granted_by", "farm_scopes_granted_by_fkey", "SET NULL"),
    ("user_preferences", "user_id", "user_preferences_user_id_fkey", "CASCADE"),
)


def upgrade() -> None:
    for table, column, name, on_delete in _FKS:
        op.execute(f'ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS "{name}"')
        op.execute(
            f"ALTER TABLE public.{table} "
            f'ADD CONSTRAINT "{name}" FOREIGN KEY ({column}) '
            f"REFERENCES public.users(id) "
            f"ON UPDATE CASCADE ON DELETE {on_delete}"
        )


def downgrade() -> None:
    for table, column, name, on_delete in _FKS:
        op.execute(f'ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS "{name}"')
        op.execute(
            f"ALTER TABLE public.{table} "
            f'ADD CONSTRAINT "{name}" FOREIGN KEY ({column}) '
            f"REFERENCES public.users(id) "
            f"ON DELETE {on_delete}"
        )
