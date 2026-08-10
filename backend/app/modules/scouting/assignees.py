"""Who on this farm can be sent on a visit.

`POST /scouting/visits/{id}:assign` takes an `assignee_user_id`, and until now
nothing returned one. `GET /farms/{id}/members` answers with farm-scope rows —
`membership_id`, `role`, timestamps — and no user id and no name, so a dispatch
UI had to fetch the whole tenant roster from `GET /users` and join the two in
the browser. That fetch needs `user.read`, which is tenant-scoped, so the
farm-level supervisor who actually needs the picker could not load it.

This is the farm-scoped answer to the same question, gated on the capability
that describes the act (`scouting.dispatch`) rather than on directory access.

Eligibility is *derived* from the capability registry rather than listed here.
The question "who can be sent on a visit" is exactly "whose farm role grants
`scouting.visit.claim`", and writing that set out by hand is how it drifts the
first time a role gains or loses the capability.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import FarmRole
from app.shared.keycloak.field_identity import is_synthetic_email
from app.shared.rbac.check import CapabilityRegistry, get_default_registry

# The capability that means "can be given a visit to do".
CLAIM_CAPABILITY = "scouting.visit.claim"


def eligible_roles(registry: CapabilityRegistry | None = None) -> tuple[str, ...]:
    """Farm roles whose holders can claim a visit, straight from the registry."""
    reg = registry or get_default_registry()
    return tuple(role.value for role in FarmRole if reg.role_grants(role.value, CLAIM_CAPABILITY))


async def list_farm_assignees(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession,
    farm_id: UUID,
) -> list[dict[str, Any]]:
    """Active members of ``farm_id`` who could be sent on a visit.

    The farm is checked against the tenant schema first. Without that a caller
    could probe ``public.farm_scopes`` for arbitrary farm ids — the same reason
    ``FarmService.list_members`` looks the farm up before reading scopes.
    """
    exists = (
        await tenant_session.execute(
            text("SELECT 1 FROM farms WHERE id = :fid").bindparams(
                bindparam("fid", type_=PG_UUID(as_uuid=True))
            ),
            {"fid": farm_id},
        )
    ).first()
    if exists is None:
        return []

    rows = (
        (
            await public_session.execute(
                text(
                    """
                    SELECT u.id           AS user_id,
                           m.id           AS membership_id,
                           u.full_name    AS full_name,
                           u.phone        AS phone,
                           u.email        AS email,
                           fs.role        AS role
                      FROM public.farm_scopes fs
                      JOIN public.tenant_memberships m ON m.id = fs.membership_id
                      JOIN public.users u ON u.id = m.user_id
                     WHERE fs.farm_id = :fid
                       AND fs.revoked_at IS NULL
                       AND m.status = 'active'
                       AND m.deleted_at IS NULL
                       AND u.deleted_at IS NULL
                       AND fs.role = ANY(:roles)
                     ORDER BY u.full_name, u.id
                    """
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id, "roles": list(eligible_roles())},
            )
        )
        .mappings()
        .all()
    )
    return [_assignee(dict(r)) for r in rows]


def _assignee(row: dict[str, Any]) -> dict[str, Any]:
    """One pickable person.

    A field worker's address is synthetic and undeliverable, so it is never
    returned — a picker that falls back to it shows `+2010…@scouts…` where a
    name should be, which reads as a data-entry error. `identity_kind` tells
    the client which of name/phone/email is the real handle.
    """
    synthetic = is_synthetic_email(row["email"])
    return {
        "user_id": row["user_id"],
        "membership_id": row["membership_id"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "email": None if synthetic else row["email"],
        "identity_kind": "phone" if synthetic else "email",
        "role": row["role"],
    }


__all__ = ["CLAIM_CAPABILITY", "eligible_roles", "list_farm_assignees"]
