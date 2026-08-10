"""FastAPI routes for the notifications module.

Mounted under /api/v1 by the app factory. PR-B endpoints:

  GET    /inbox                      â€” current user's inbox
  GET    /inbox/unread-count         â€” bell badge feed
  PATCH  /inbox/{item_id}            â€” mark read / archive

PR-C will add ``GET /inbox/stream`` (SSE).

RBAC:
  * ``notification.read_inbox`` â€” every tenant role grants this.
  * ``notification.write_inbox`` â€” same; "write" here is just
    read/archive on one's own items.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.notifications.devices import list_devices, register_device, revoke_device
from app.modules.notifications.errors import InboxItemNotFoundError
from app.modules.notifications.schemas import (
    DeviceRegisterRequest,
    DeviceResponse,
    InboxItemResponse,
    InboxTransitionRequest,
    InboxUnreadCountResponse,
)
from app.modules.notifications.service import (
    NotificationsServiceImpl,
    get_notifications_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability
from app.shared.realtime import subscribe as realtime_subscribe

router = APIRouter(prefix="/api/v1", tags=["notifications"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> NotificationsServiceImpl:
    return get_notifications_service(tenant_session=tenant_session, public_session=public_session)


def _ensure_user(context: RequestContext) -> UUID:
    if context.user_id is None or context.tenant_schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return context.user_id


@router.get(
    "/inbox",
    response_model=list[InboxItemResponse],
    summary="Current user's in-app inbox.",
)
async def list_inbox(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("notification.read_inbox")),
    service: NotificationsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    user_id = _ensure_user(context)
    rows = await service.list_inbox(user_id=user_id, include_archived=include_archived, limit=limit)
    return list(rows)


@router.get(
    "/inbox/unread-count",
    response_model=InboxUnreadCountResponse,
    summary="Count of unread inbox items for the bell-icon badge.",
)
async def get_unread_count(
    context: RequestContext = Depends(requires_capability("notification.read_inbox")),
    service: NotificationsServiceImpl = Depends(_service),
) -> dict[str, int]:
    user_id = _ensure_user(context)
    count = await service.count_unread(user_id=user_id)
    return {"count": count}


@router.get(
    "/inbox/stream",
    summary="Server-Sent Events stream of new inbox items for the current user.",
)
async def stream_inbox(
    context: RequestContext = Depends(requires_capability("notification.read_inbox")),
) -> StreamingResponse:
    """Yields ``event: inbox\\ndata: <json>\\n\\n`` per push.

    Auth piggybacks on the standard JWT middleware â€” clients pass the
    bearer token via ``fetch`` (``EventSource`` does not support custom
    headers natively). On disconnect, the underlying Redis subscription
    is closed.
    """
    user_id = _ensure_user(context)
    tenant_id = context.tenant_id
    assert tenant_id is not None  # _ensure_user checked tenant_schema

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable nginx buffering
    }
    return StreamingResponse(
        realtime_subscribe(tenant_id=tenant_id, user_id=user_id),
        media_type="text/event-stream",
        headers=headers,
    )


@router.patch(
    "/inbox/{item_id}",
    response_model=InboxItemResponse,
    summary="Mark inbox item read / archive it.",
)
async def transition_inbox_item(
    item_id: UUID,
    payload: InboxTransitionRequest,
    context: RequestContext = Depends(requires_capability("notification.write_inbox")),
    service: NotificationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    user_id = _ensure_user(context)
    schema = context.tenant_schema
    assert schema is not None  # _ensure_user checked tenant_schema
    updated = await service.transition_inbox_item(
        item_id=item_id, user_id=user_id, action=payload.action, tenant_schema=schema
    )
    item = await service.get_inbox_item(item_id=item_id, user_id=user_id)
    if item is None:
        raise InboxItemNotFoundError(item_id)
    # If updated == False the action was a no-op (already read / archived);
    # we still return the current row.
    _ = updated
    return item


# ---------- Devices (push channel) ------------------------------------------
#
# Gated on `notification.write_inbox` rather than a new capability: every role
# that can receive notifications already holds it, including Scout, and
# registering the handset you are already signed in on is the same class of
# act as marking your own inbox item read. A separate capability would have to
# be granted to all seven roles on day one to be useful, which is a capability
# that distinguishes nothing.


@router.post(
    "/devices:register",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register (or refresh) this device's push token.",
)
async def register_device_endpoint(
    payload: DeviceRegisterRequest,
    context: RequestContext = Depends(requires_capability("notification.write_inbox")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user_id = _ensure_user(context)
    return await register_device(
        tenant_session,
        user_id=user_id,
        token=payload.token,
        platform=payload.platform,
        app_version=payload.app_version,
        locale=payload.locale,
    )


@router.get(
    "/devices",
    response_model=list[DeviceResponse],
    summary="Devices currently registered to the caller.",
)
async def list_devices_endpoint(
    context: RequestContext = Depends(requires_capability("notification.read_inbox")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    user_id = _ensure_user(context)
    return list(await list_devices(tenant_session, user_id=user_id))


@router.delete(
    "/devices/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Stop pushing to one of the caller's devices (sign-out).",
)
async def revoke_device_endpoint(
    token: str,
    context: RequestContext = Depends(requires_capability("notification.write_inbox")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> None:
    user_id = _ensure_user(context)
    revoked = await revoke_device(tenant_session, user_id=user_id, token=token)
    if not revoked:
        # 404 rather than 204: sign-out that silently did nothing is how a
        # handset keeps receiving a farm's alerts after its owner left.
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Device not found",
            detail="No live device with that token is registered to you.",
            type_="https://agripulse.cloud/problems/device-not-found",
        )
