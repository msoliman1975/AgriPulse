"""Notifications service — async surface for the API process.

Two responsibilities:

  * **Inbox reads / transitions** for the bell-icon endpoints
    (``/api/v1/inbox*``).
  * **Dispatch entry point** — exposed for the cross-module subscriber
    (which calls the *sync* path from ``subscribers.py``) and for
    direct API calls in the future.

PR-B wires only the in-app channel; email/webhook senders are stubs
that mark dispatches ``skipped``. PR-D and PR-E replace those with
real I/O.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import AuditService, get_audit_service
from app.modules.notifications.repository import NotificationsRepository


class NotificationsService(Protocol):
    """Public contract."""

    async def list_inbox(
        self, *, user_id: UUID, include_archived: bool, limit: int
    ) -> tuple[dict[str, Any], ...]: ...

    async def count_unread(self, *, user_id: UUID) -> int: ...

    async def get_inbox_item(self, *, item_id: UUID, user_id: UUID) -> dict[str, Any] | None: ...

    async def transition_inbox_item(
        self, *, item_id: UUID, user_id: UUID, action: str, tenant_schema: str
    ) -> bool: ...


class NotificationsServiceImpl:
    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        public_session: AsyncSession,
        audit_service: AuditService | None = None,
    ) -> None:
        self._tenant = tenant_session
        self._public = public_session
        self._repo = NotificationsRepository(
            tenant_session=tenant_session, public_session=public_session
        )
        self._audit = audit_service or get_audit_service()

    async def list_inbox(
        self, *, user_id: UUID, include_archived: bool = False, limit: int = 100
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_inbox(
            user_id=user_id, include_archived=include_archived, limit=limit
        )

    async def count_unread(self, *, user_id: UUID) -> int:
        return await self._repo.count_unread(user_id=user_id)

    async def get_inbox_item(self, *, item_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        return await self._repo.get_inbox_item(item_id=item_id, user_id=user_id)

    async def transition_inbox_item(
        self, *, item_id: UUID, user_id: UUID, action: str, tenant_schema: str
    ) -> bool:
        changed = await self._repo.transition_inbox_item(
            item_id=item_id, user_id=user_id, action=action
        )
        # Only emit an audit row when state actually flipped — re-marking
        # an already-read item read is a UI no-op, not a meaningful event.
        if changed:
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type=f"notifications.inbox_{action}",
                actor_user_id=user_id,
                subject_kind="inbox_item",
                subject_id=item_id,
                farm_id=None,
                details={"action": action},
            )
        return changed


def get_notifications_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> NotificationsServiceImpl:
    return NotificationsServiceImpl(tenant_session=tenant_session, public_session=public_session)


# Type-checker assist.
def _check(impl: NotificationsServiceImpl) -> NotificationsService:
    return impl


__all__ = [
    "NotificationsService",
    "NotificationsServiceImpl",
    "get_notifications_service",
    "datetime",
]
