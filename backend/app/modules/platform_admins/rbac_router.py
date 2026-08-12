"""The RBAC matrix endpoint, and the runtime edits that layer over it.

Mounted at /api/v1/admin/rbac.

  GET    /matrix                                  — every role, every capability
  PUT    /roles/{role}/capabilities/{capability}  — grant or revoke
  DELETE /roles/{role}/capabilities/{capability}  — reset to the shipped default
  GET    /changes                                 — the change trail

Reads are gated on `platform.read` — the matrix is policy documentation, the
same bar platform defaults uses. **Writes need `platform.manage_rbac`**, which
nothing but PlatformAdmin's wildcard holds by default: a write rewrites
authorization for every tenant at once.

`PlatformAdmin` is refused here *and* dropped by `overlay._load`. Two
independent guards, because this is the one edit that could lock every
administrator out of the page that would undo it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admins.rbac_service import (
    ChangeLogRow,
    OverrideResult,
    RbacMatrixResponse,
    apply_override,
    build_matrix,
    clear_override,
    list_changes,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import has_capability, requires_capability
from app.shared.rbac.overlay import invalidate as invalidate_overlay

router = APIRouter(prefix="/api/v1/admin/rbac", tags=["admin-rbac"])

MANAGE = "platform.manage_rbac"


class OverrideRequest(BaseModel):
    granted: bool
    #: Why. Free text, surfaced in the change log — the trail is worth little
    #: without it, but it is not forced: an admin fixing a live 403 should not
    #: be blocked on composing a sentence.
    note: str | None = Field(default=None, max_length=500)


@router.get("/matrix", response_model=RbacMatrixResponse)
async def get_rbac_matrix(
    session: AsyncSession = Depends(get_admin_db_session),
    context: RequestContext = Depends(requires_capability("platform.read")),
) -> RbacMatrixResponse:
    """The role -> capability matrix, with per-role holder counts.

    Grants are effective (baseline + overrides), so this agrees with what the
    resolver would answer for the same pair.
    """
    return await build_matrix(
        session,
        can_manage=has_capability(context, MANAGE),
    )


@router.put(
    "/roles/{role}/capabilities/{capability}",
    response_model=OverrideResult,
    summary="Grant or revoke a capability on a role at runtime.",
)
async def set_capability_override(
    role: str,
    capability: str,
    payload: OverrideRequest,
    session: AsyncSession = Depends(get_admin_db_session),
    context: RequestContext = Depends(requires_capability(MANAGE)),
) -> OverrideResult:
    result = await apply_override(
        session,
        role=role,
        capability=capability,
        granted=payload.granted,
        actor_id=context.user_id,
        actor_email=context.email,
        note=payload.note,
    )
    # Mark the snapshot stale rather than reloading it here. The request-scoped
    # `session.begin()` does not commit until this route returns, so an eager
    # reload would read the *pre-write* state and then hold it for a full TTL —
    # the exact staleness this hook exists to avoid. Invalidating is
    # synchronous and order-independent: the next request through this pod
    # reloads, by which time the write has landed. Other pods follow within the
    # TTL. Mirrors `settings.resolver.invalidate_defaults_cache()`.
    invalidate_overlay()
    return result


@router.delete(
    "/roles/{role}/capabilities/{capability}",
    response_model=OverrideResult,
    summary="Reset a role's capability to the shipped default.",
)
async def reset_capability_override(
    role: str,
    capability: str,
    note: Annotated[str | None, Query(max_length=500)] = None,
    session: AsyncSession = Depends(get_admin_db_session),
    context: RequestContext = Depends(requires_capability(MANAGE)),
) -> OverrideResult:
    result = await clear_override(
        session,
        role=role,
        capability=capability,
        actor_id=context.user_id,
        actor_email=context.email,
        note=note,
    )
    invalidate_overlay()  # see set_capability_override
    return result


@router.get(
    "/changes",
    response_model=list[ChangeLogRow],
    summary="Runtime RBAC changes, newest first.",
)
async def get_rbac_changes(
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    session: AsyncSession = Depends(get_admin_db_session),
    _: RequestContext = Depends(requires_capability("platform.read")),
) -> list[ChangeLogRow]:
    """Append-only history, including resets — whose override rows are gone."""
    return await list_changes(session, limit=limit)
