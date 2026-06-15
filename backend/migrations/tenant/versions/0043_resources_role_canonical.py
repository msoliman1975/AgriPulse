"""U-2 (identity unification) — canonicalise worker role vocabulary.

Worker `role` values move from the standalone lowercase set
(``agronomist | operator | scout | field_worker | manager``) to the
canonical agronomic vocabulary shared with the IAM per-farm roles
(``app.shared.auth.context.FarmRole``):

    agronomist   -> Agronomist     (== FarmRole.AGRONOMIST)
    operator     -> FieldOperator  (== FarmRole.FIELD_OPERATOR)
    scout        -> Scout          (== FarmRole.SCOUT)
    manager      -> FarmManager    (== FarmRole.FARM_MANAGER)
    field_worker -> FieldWorker    (worker-only: generic labour, no login)

Four of the five now match a FarmRole member exactly, so a login member
holding a farm-scope and a no-login worker record speak the same role
language — reporting and pickers no longer hand-map two vocabularies.

The change is value-only: the `role` column stays ``Text`` and the
``ck_resources_role`` CHECK is swapped for the new allowed set. A
deterministic ``UPDATE`` backfills existing rows, so this is reversible
with no data loss (downgrade maps the canonical values back).

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep in lockstep with app/modules/resources/schemas.py::WorkerRole.
_CANONICAL_ROLE_VALUES = ("FarmManager", "Agronomist", "FieldOperator", "Scout", "FieldWorker")
_LEGACY_ROLE_VALUES = ("agronomist", "operator", "scout", "field_worker", "manager")

# legacy -> canonical (upgrade) and its inverse (downgrade).
_FORWARD = {
    "agronomist": "Agronomist",
    "operator": "FieldOperator",
    "scout": "Scout",
    "field_worker": "FieldWorker",
    "manager": "FarmManager",
}
_BACKWARD = {new: old for old, new in _FORWARD.items()}


def _swap_role_check(*, allowed: tuple[str, ...], mapping: dict[str, str]) -> None:
    """Drop the role CHECK, remap values, re-add the CHECK with `allowed`.

    Dropping the constraint first lets the UPDATE land values that the
    current CHECK would reject; re-adding it after pins the new contract.
    """
    op.execute("ALTER TABLE resources DROP CONSTRAINT IF EXISTS ck_resources_role")
    # One CASE per direction. role IS NULL (equipment rows) is left alone.
    whens = "\n".join(f"WHEN '{src}' THEN '{dst}'" for src, dst in mapping.items())
    op.execute(
        f"""
        UPDATE resources
        SET role = CASE role
        {whens}
        ELSE role
        END
        WHERE role IS NOT NULL
        """
    )
    allowed_sql = ", ".join(f"'{v}'" for v in allowed)
    op.execute(
        f"ALTER TABLE resources ADD CONSTRAINT ck_resources_role "
        f"CHECK (role IS NULL OR role IN ({allowed_sql}))"
    )


def upgrade() -> None:
    _swap_role_check(allowed=_CANONICAL_ROLE_VALUES, mapping=_FORWARD)


def downgrade() -> None:
    _swap_role_check(allowed=_LEGACY_ROLE_VALUES, mapping=_BACKWARD)
