"""Allow the InvestmentManager and Investor roles in tenant_role_assignments.

InvestmentManager is the staff role that runs the Investments area
(investors, holdings, ownership). Investor is the outside owner of holdings;
the investors module grants it when staff create an investor's app login.
Both are tenant-tier roles, so they live in tenant_role_assignments, whose
CHECK last changed in 0036.

Same drop-and-recreate as 0036: the constraint's real name is
convention-doubled, so it is dropped by that name with IF EXISTS and
re-added through create_check_constraint, which applies the convention again.

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0101"
down_revision: str | Sequence[str] | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REAL_NAME = "ck_tenant_role_assignments_ck_tenant_role_assignments_role"
_WITH_INVESTMENTS = (
    "role IN ('TenantOwner','TenantAdmin','BillingAdmin','Viewer',"
    "'InvestmentManager','Investor')"
)
_BEFORE = "role IN ('TenantOwner','TenantAdmin','BillingAdmin','Viewer')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE public.tenant_role_assignments DROP CONSTRAINT IF EXISTS {_REAL_NAME}")
    op.create_check_constraint(
        "ck_tenant_role_assignments_role",
        "tenant_role_assignments",
        _WITH_INVESTMENTS,
        schema="public",
    )


def downgrade() -> None:
    # NOT VALID: the old CHECK applies to new writes only. Rows that hold one
    # of the two roles stay as they are; deleting them would take a person's
    # access with no trace, and refusing the downgrade breaks the migration
    # round-trip tests that run after rows like these were written.
    op.execute(f"ALTER TABLE public.tenant_role_assignments DROP CONSTRAINT IF EXISTS {_REAL_NAME}")
    op.execute(
        f"ALTER TABLE public.tenant_role_assignments ADD CONSTRAINT {_REAL_NAME} "
        f"CHECK ({_BEFORE}) NOT VALID"
    )
