"""Read-only RBAC matrix endpoint.

Mounted at /api/v1/admin/rbac. Gated on `platform.read` — the same bar
platform defaults uses for reads, since the matrix is policy documentation
rather than tenant data.

  GET /api/v1/admin/rbac/matrix   — every role, every capability, holder counts

Phase 2 adds the write endpoints here; the read shape is designed so a
`granted` toggle can be layered on without changing the payload contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admins.rbac_service import RbacMatrixResponse, build_matrix
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/rbac", tags=["admin-rbac"])


@router.get("/matrix", response_model=RbacMatrixResponse)
async def get_rbac_matrix(
    session: AsyncSession = Depends(get_admin_db_session),
    _: RequestContext = Depends(requires_capability("platform.read")),
) -> RbacMatrixResponse:
    """The role -> capability matrix, with per-role holder counts."""
    return await build_matrix(session)
