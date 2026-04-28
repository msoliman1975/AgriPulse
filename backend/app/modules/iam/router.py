"""FastAPI router: GET /api/v1/me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.iam.schemas import MeResponse
from app.modules.iam.service import UserNotFoundError, UserService, get_user_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session

router = APIRouter(prefix="/api/v1", tags=["iam"])


def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> UserService:
    return get_user_service(session)


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user profile, preferences, and authorization scopes.",
)
async def get_me(
    context: RequestContext = Depends(get_current_context),
    service: UserService = Depends(_service),
) -> MeResponse:
    try:
        return await service.get_me(context.user_id)
    except UserNotFoundError as exc:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="User not found",
            detail="No user record exists for this token. Sign out and back in.",
            type_="https://missionagre.io/problems/user-not-found",
        ) from exc
