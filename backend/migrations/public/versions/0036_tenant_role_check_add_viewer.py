"""Allow 'Viewer' in the tenant_role_assignments role CHECK.

`Viewer` is the DEFAULT tenant role (UserInviteRequest.tenant_role defaults to
it and the invite UI selects it by default), but the original CHECK from 0003
only allowed ('TenantOwner','TenantAdmin','BillingAdmin'). So every
default-role invite hit a CheckViolationError -> 500 and never created the
user. Add 'Viewer' to the allowed set.

The constraint's real name is convention-doubled
(`ck_tenant_role_assignments_ck_tenant_role_assignments_role`) because 0003
defined it inline in create_table with name="ck_tenant_role_assignments_role"
and the metadata naming convention prefixes it again. Drop by the real name
with IF EXISTS (and re-add via create_check_constraint, which re-applies the
convention) so this stays idempotent for the session-shared roundtrip tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REAL_NAME = "ck_tenant_role_assignments_ck_tenant_role_assignments_role"
_WITH_VIEWER = "role IN ('TenantOwner','TenantAdmin','BillingAdmin','Viewer')"
_WITHOUT_VIEWER = "role IN ('TenantOwner','TenantAdmin','BillingAdmin')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE public.tenant_role_assignments DROP CONSTRAINT IF EXISTS {_REAL_NAME}")
    op.create_check_constraint(
        "ck_tenant_role_assignments_role",
        "tenant_role_assignments",
        _WITH_VIEWER,
        schema="public",
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.tenant_role_assignments DROP CONSTRAINT IF EXISTS {_REAL_NAME}")
    op.create_check_constraint(
        "ck_tenant_role_assignments_role",
        "tenant_role_assignments",
        _WITHOUT_VIEWER,
        schema="public",
    )
