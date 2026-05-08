"""Async DB access for the notifications module. Internal to the module.

The dispatcher writes through this layer; the router reads through it.
Sync paths (cross-module subscriber on ``AlertOpenedV1``) do their own
session management — see ``subscribers.py`` — so they don't pull in the
async session this repository assumes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class NotificationsRepository:
    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        self._public = public_session

    # ---- inbox -------------------------------------------------------

    async def list_inbox(
        self,
        *,
        user_id: UUID,
        include_archived: bool = False,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["deleted_at IS NULL", "user_id = :uid"]
        if not include_archived:
            clauses.append("archived_at IS NULL")
        # Static literals — no caller-supplied SQL fragments.
        sql = (
            "SELECT id, alert_id, recommendation_id, severity, title, body, "
            "       link_url, read_at, archived_at, created_at "
            "FROM in_app_inbox "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY created_at DESC LIMIT :limit"
        )
        rows = (
            (
                await self._tenant.execute(
                    text(sql).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                    {"uid": user_id, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def count_unread(self, *, user_id: UUID) -> int:
        row = (
            await self._tenant.execute(
                text(
                    "SELECT count(*) AS c FROM in_app_inbox "
                    "WHERE user_id = :uid AND read_at IS NULL "
                    "  AND archived_at IS NULL AND deleted_at IS NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).first()
        return int(row.c) if row is not None else 0

    async def get_inbox_item(self, *, item_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._tenant.execute(
                    text(
                        "SELECT id, alert_id, recommendation_id, severity, title, body, "
                        "       link_url, read_at, archived_at, created_at "
                        "FROM in_app_inbox "
                        "WHERE id = :iid AND user_id = :uid AND deleted_at IS NULL"
                    ).bindparams(
                        bindparam("iid", type_=PG_UUID(as_uuid=True)),
                        bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"iid": item_id, "uid": user_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def transition_inbox_item(self, *, item_id: UUID, user_id: UUID, action: str) -> bool:
        """Apply ``read`` or ``archive`` to the item if it's owned by user_id.
        Returns True iff a row was updated."""
        if action == "read":
            sql = (
                "UPDATE in_app_inbox SET read_at = now(), updated_at = now() "
                "WHERE id = :iid AND user_id = :uid AND read_at IS NULL "
                "  AND deleted_at IS NULL"
            )
        elif action == "archive":
            sql = (
                "UPDATE in_app_inbox SET archived_at = now(), updated_at = now() "
                "WHERE id = :iid AND user_id = :uid AND archived_at IS NULL "
                "  AND deleted_at IS NULL"
            )
        else:
            raise ValueError(f"unknown action {action!r}")
        result = await self._tenant.execute(
            text(sql).bindparams(
                bindparam("iid", type_=PG_UUID(as_uuid=True)),
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
            ),
            {"iid": item_id, "uid": user_id},
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    # ---- templates (read-through cache could go here later) ----------

    async def get_template(
        self, *, template_code: str, locale: str, channel: str
    ) -> dict[str, Any] | None:
        """Fetch the latest version of a template, falling back to ``en``
        when the requested locale is missing.
        """
        for try_locale in (locale, "en"):
            row = (
                (
                    await self._public.execute(
                        text(
                            "SELECT subject, body, body_html, version "
                            "FROM public.notification_templates "
                            "WHERE template_code = :code AND locale = :loc "
                            "  AND channel = :chan "
                            "ORDER BY version DESC LIMIT 1"
                        ),
                        {"code": template_code, "loc": try_locale, "chan": channel},
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                return dict(row)
        return None

    # ---- dispatch records --------------------------------------------

    async def insert_dispatch(
        self,
        *,
        dispatch_id: UUID,
        alert_id: UUID | None,
        recommendation_id: UUID | None,
        template_code: str,
        locale: str,
        channel: str,
        recipient_user_id: UUID | None,
        recipient_address: str | None,
        status: str,
        rendered_subject: str | None,
        rendered_body: str | None,
        error: str | None,
    ) -> bool:
        """Insert a dispatch row. Returns True on insert, False on the
        idempotency partial-UNIQUE collision (already pending or sent).
        """
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO notification_dispatches (
                        id, alert_id, recommendation_id,
                        template_code, locale, channel,
                        recipient_user_id, recipient_address,
                        status, rendered_subject, rendered_body, error,
                        sent_at
                    ) VALUES (
                        :id, :alert_id, :rec_id,
                        :code, :loc, :chan,
                        :uid, :addr,
                        :status, :rs, :rb, :err,
                        CASE WHEN :status = 'sent' THEN now() ELSE NULL END
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("alert_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("rec_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": dispatch_id,
                    "alert_id": alert_id,
                    "rec_id": recommendation_id,
                    "code": template_code,
                    "loc": locale,
                    "chan": channel,
                    "uid": recipient_user_id,
                    "addr": recipient_address,
                    "status": status,
                    "rs": rendered_subject,
                    "rb": rendered_body,
                    "err": error,
                },
            )
        except IntegrityError as exc:
            if "uq_notification_dispatches_alert_chan_user_active" in str(exc):
                return False
            raise
        return True

    async def insert_inbox_item(
        self,
        *,
        item_id: UUID,
        user_id: UUID,
        alert_id: UUID | None,
        recommendation_id: UUID | None,
        severity: str | None,
        title: str,
        body: str,
        link_url: str | None,
        created_at: datetime | None = None,
    ) -> None:
        await self._tenant.execute(
            text(
                """
                INSERT INTO in_app_inbox (
                    id, user_id, alert_id, recommendation_id,
                    severity, title, body, link_url,
                    created_at, updated_at
                ) VALUES (
                    :id, :uid, :alert_id, :rec_id,
                    :sev, :title, :body, :link,
                    COALESCE(:created, now()), now()
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
                bindparam("alert_id", type_=PG_UUID(as_uuid=True)),
                bindparam("rec_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": item_id,
                "uid": user_id,
                "alert_id": alert_id,
                "rec_id": recommendation_id,
                "sev": severity,
                "title": title,
                "body": body,
                "link": link_url,
                "created": created_at or datetime.now(UTC),
            },
        )
