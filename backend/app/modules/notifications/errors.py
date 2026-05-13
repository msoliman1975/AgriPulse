"""Notification module errors."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import APIError


class InboxItemNotFoundError(APIError):
    def __init__(self, item_id: UUID) -> None:
        super().__init__(
            status_code=404,
            title="Inbox item not found",
            detail=f"No inbox item with id {item_id}.",
            type_="https://agripulse.cloud/problems/inbox-item-not-found",
        )


class TemplateNotFoundError(APIError):
    def __init__(self, template_code: str, locale: str, channel: str) -> None:
        super().__init__(
            status_code=500,
            title="Notification template missing",
            detail=(
                f"No notification_templates row for "
                f"({template_code!r}, {locale!r}, {channel!r})."
            ),
            type_="https://agripulse.cloud/problems/notification-template-missing",
        )
