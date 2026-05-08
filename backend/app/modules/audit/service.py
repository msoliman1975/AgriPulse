"""Audit service: write domain events to the tenant's `audit_events` hypertable.

`AuditService.record(...)` is the single place every module routes audit
writes through. Per data_model § 13.2 the table is append-only — the
service exposes only INSERT.

A separate session is opened per call with ``search_path`` pinned to the
target tenant's schema (the recorder may be invoked from contexts whose
ambient session is on `public`, e.g., from the tenancy admin endpoint).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit.models import AuditEvent, AuditEventArchive
from app.shared.db.ids import uuid7
from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema


class AuditService(Protocol):
    """Public contract for the audit module."""

    async def record(
        self,
        *,
        tenant_schema: str,
        event_type: str,
        actor_user_id: UUID | None,
        subject_kind: str,
        subject_id: UUID,
        details: dict[str, Any],
        farm_id: UUID | None = None,
        correlation_id: UUID | None = None,
        actor_kind: str = "user",
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> UUID: ...

    async def record_archive(
        self,
        *,
        event_type: str,
        actor_user_id: UUID | None,
        subject_kind: str,
        subject_id: UUID,
        details: dict[str, Any],
        correlation_id: UUID | None = None,
        actor_kind: str = "user",
    ) -> UUID: ...


class AuditServiceImpl:
    def __init__(self) -> None:
        self._log = get_logger(__name__)

    async def record(
        self,
        *,
        tenant_schema: str,
        event_type: str,
        actor_user_id: UUID | None,
        subject_kind: str,
        subject_id: UUID,
        details: dict[str, Any],
        farm_id: UUID | None = None,
        correlation_id: UUID | None = None,
        actor_kind: str = "user",
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        safe_schema = sanitize_tenant_schema(tenant_schema)
        if actor_kind == "user" and actor_user_id is None:
            actor_kind = "system"

        event_id = uuid7()
        when = datetime.now(UTC)

        factory = AsyncSessionLocal()
        async with factory() as session, session.begin():
            await session.execute(text(f"SET LOCAL search_path TO {safe_schema}, public"))
            session.add(
                AuditEvent(
                    time=when,
                    id=event_id,
                    event_type=event_type,
                    actor_user_id=actor_user_id,
                    actor_kind=actor_kind,
                    correlation_id=correlation_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    farm_id=farm_id,
                    details=details,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            )

        self._log.info(
            "audit_recorded",
            event_type=event_type,
            subject_kind=subject_kind,
            subject_id=str(subject_id),
            tenant_schema=safe_schema,
        )
        return event_id

    async def record_archive(
        self,
        *,
        event_type: str,
        actor_user_id: UUID | None,
        subject_kind: str,
        subject_id: UUID,
        details: dict[str, Any],
        correlation_id: UUID | None = None,
        actor_kind: str = "user",
    ) -> UUID:
        if actor_kind == "user" and actor_user_id is None:
            actor_kind = "system"

        event_id = uuid7()
        when = datetime.now(UTC)

        factory = AsyncSessionLocal()
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL search_path TO public"))
            session.add(
                AuditEventArchive(
                    id=event_id,
                    occurred_at=when,
                    event_type=event_type,
                    actor_user_id=actor_user_id,
                    actor_kind=actor_kind,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    details=details,
                    correlation_id=correlation_id,
                )
            )

        self._log.info(
            "audit_archive_recorded",
            event_type=event_type,
            subject_kind=subject_kind,
            subject_id=str(subject_id),
        )
        return event_id


_default: AuditService | None = None


def get_audit_service() -> AuditService:
    global _default
    if _default is None:
        _default = AuditServiceImpl()
    return _default


# Allow tests to inject a fake.
def set_audit_service(impl: AuditService | None) -> None:
    global _default
    _default = impl


# AsyncSession imported only to keep type-checkers happy when the
# Protocol type-hints reference it indirectly.
_ = AsyncSession
