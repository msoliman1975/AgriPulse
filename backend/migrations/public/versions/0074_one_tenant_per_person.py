"""One person belongs to exactly one tenant.

`uq_tenant_memberships_user_tenant` is on `(user_id, tenant_id)`. It stops a
person being added to the *same* tenant twice and permits them being added to
as many *different* tenants as you like — which is the case nothing in the
system handles.

The reason it cannot work is one attribute. `tenant_id` is a single-valued
Keycloak user attribute and the JWT carries one value, so a request resolves
exactly one tenant schema. `farm_scopes` is multi-valued and is rebuilt from
every membership the user holds, because writing one tenant's scopes would
delete the other's. So a second membership produces a token that names farms
in a tenant it cannot reach: the API authorizes the farm (the scope is in the
token) and then looks for it in the wrong schema. Nothing errors. The mobile
app has carried a `failed` list for exactly these farms.

This index makes the rule the database's, so no future write path has to
remember it:

    tenant_memberships (user_id) WHERE deleted_at IS NULL

Partial on `deleted_at`, because offboarding soft-deletes the membership
(`users_service.delete_user` sets `deleted_at` and `status = 'archived'`).
A person who leaves one tenant can still be invited by another, which is a
real case and must keep working.

## This migration refuses to run on dirty data

A person holding two live memberships has to lose one, and which one is a
decision about that person's job — not something a migration may take. The
check below raises with the offending emails rather than archiving the newer
row, silently picking the tenant their Keycloak attribute happens to name, or
creating the index `CONCURRENTLY` and leaving it INVALID.

To clear it, for each person named in the error, archive the membership they
are not keeping through the offboarding path so the farm scopes and role
grants are revoked with it:

    DELETE /api/v1/users/{user_id}?  -- the tenant admin surface, or
    UPDATE public.tenant_memberships
       SET deleted_at = now(), status = 'archived'
     WHERE id = '<membership to drop>';
    UPDATE public.farm_scopes SET revoked_at = now()
     WHERE membership_id = '<membership to drop>' AND revoked_at IS NULL;
    UPDATE public.tenant_role_assignments SET revoked_at = now()
     WHERE membership_id = '<membership to drop>' AND revoked_at IS NULL;

Then re-sync that user's `farm_scopes` attribute in Keycloak, or the token
keeps granting the farm the row above just revoked. The API path that does
this is `TenantUsersService._sync_scopes_and_end_sessions`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | Sequence[str] | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_tenant_memberships_one_live_per_user"

_OFFENDERS = sa.text(
    """
    SELECT u.email                                AS email,
           u.id                                   AS user_id,
           count(*)                               AS memberships,
           string_agg(t.slug, ', ' ORDER BY m.created_at) AS tenants
      FROM public.tenant_memberships m
      JOIN public.users u   ON u.id = m.user_id
      JOIN public.tenants t ON t.id = m.tenant_id
     WHERE m.deleted_at IS NULL
     GROUP BY u.id, u.email
    HAVING count(*) > 1
     ORDER BY u.email
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(_OFFENDERS).mappings().all()
    if rows:
        listed = "\n".join(
            f"  {r['email']} ({r['user_id']}): {r['memberships']} memberships — {r['tenants']}"
            for r in rows
        )
        raise RuntimeError(
            "Cannot enforce one tenant per person: "
            f"{len(rows)} user(s) hold more than one live membership.\n"
            f"{listed}\n"
            "Archive the membership each person is not keeping, then re-run. "
            "See the docstring of this migration for the statements."
        )

    op.create_index(
        INDEX_NAME,
        "tenant_memberships",
        ["user_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="tenant_memberships", schema="public")
