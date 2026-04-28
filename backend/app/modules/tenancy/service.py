"""Tenancy service: public Protocol + concrete implementation.

Other modules depend on the `TenantService` Protocol, never on
`TenantServiceImpl`. The concrete impl is wired in
`app.core.app_factory` (or in tests, with stubs).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.tenancy.bootstrap import AlembicTenantMigrator, TenantSchemaMigrator
from app.modules.tenancy.events import TenantCreatedV1
from app.modules.tenancy.repository import TenantRepository
from app.shared.db.ids import schema_name_for, uuid7
from app.shared.eventbus import EventBus, get_default_bus


class TenantService(Protocol):
    """Public contract for the tenancy module."""

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        contact_email: str,
        legal_name: str | None = None,
        tax_id: str | None = None,
        contact_phone: str | None = None,
        default_locale: str = "en",
        default_unit_system: str = "feddan",
        initial_tier: str = "free",
        actor_user_id: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> "TenantCreatedResult": ...


class TenantCreatedResult:
    """Plain DTO returned from create_tenant."""

    __slots__ = (
        "tenant_id",
        "slug",
        "name",
        "schema_name",
        "contact_email",
        "default_locale",
        "default_unit_system",
        "status",
        "created_at",
    )

    def __init__(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        name: str,
        schema_name: str,
        contact_email: str,
        default_locale: str,
        default_unit_system: str,
        status: str,
        created_at: datetime,
    ) -> None:
        self.tenant_id = tenant_id
        self.slug = slug
        self.name = name
        self.schema_name = schema_name
        self.contact_email = contact_email
        self.default_locale = default_locale
        self.default_unit_system = default_unit_system
        self.status = status
        self.created_at = created_at


class SlugAlreadyExistsError(ValueError):
    """Raised when create_tenant is called with a slug already in use."""


class TenantServiceImpl:
    """Concrete TenantService — async session injected per call.

    The session is the admin session (search_path = public only). Schema
    bootstrap (CREATE SCHEMA + alembic upgrade) runs *after* the DB
    transaction commits, so a failed insert never leaves an orphan schema.
    A failed bootstrap leaves the tenant row but no schema — recoverable
    via `scripts/migrate_tenants.py`.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
        migrator: TenantSchemaMigrator | None = None,
    ) -> None:
        self._session = session
        self._repo = TenantRepository(session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._migrator = migrator or AlembicTenantMigrator()
        self._log = get_logger(__name__)

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        contact_email: str,
        legal_name: str | None = None,
        tax_id: str | None = None,
        contact_phone: str | None = None,
        default_locale: str = "en",
        default_unit_system: str = "feddan",
        initial_tier: str = "free",
        actor_user_id: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> TenantCreatedResult:
        if await self._repo.slug_exists(slug):
            raise SlugAlreadyExistsError(f"tenant slug already in use: {slug!r}")

        tenant_id = uuid7()
        schema_name = schema_name_for(tenant_id)

        tenant = await self._repo.insert_tenant(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            contact_email=contact_email,
            schema_name=schema_name,
            legal_name=legal_name,
            tax_id=tax_id,
            contact_phone=contact_phone,
            default_locale=default_locale,
            default_unit_system=default_unit_system,
            actor_user_id=actor_user_id,
        )
        await self._repo.insert_settings(
            tenant_id=tenant_id, actor_user_id=actor_user_id
        )
        await self._repo.insert_subscription(
            tenant_id=tenant_id,
            tier=initial_tier,
            actor_user_id=actor_user_id,
        )

        # Flush only — caller's session.begin() context will commit.
        await self._session.flush()

        # Bootstrap the schema (sync DDL + Alembic) off the event loop.
        await asyncio.to_thread(self._migrator.bootstrap, schema_name)

        await self._audit.record(
            tenant_schema=schema_name,
            event_type="tenancy.tenant_created",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={
                "slug": slug,
                "schema_name": schema_name,
                "initial_tier": initial_tier,
            },
            correlation_id=correlation_id,
        )

        self._bus.publish(
            TenantCreatedV1(
                tenant_id=tenant_id,
                slug=slug,
                schema_name=schema_name,
                contact_email=contact_email,
                created_at=tenant.created_at or datetime.now(timezone.utc),
                actor_user_id=actor_user_id,
            )
        )

        self._log.info(
            "tenant_created",
            tenant_id=str(tenant_id),
            slug=slug,
            schema=schema_name,
        )

        return TenantCreatedResult(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            schema_name=schema_name,
            contact_email=contact_email,
            default_locale=default_locale,
            default_unit_system=default_unit_system,
            status=tenant.status,
            created_at=tenant.created_at or datetime.now(timezone.utc),
        )


def get_tenant_service(
    session: AsyncSession,
    *,
    audit_service: AuditService | None = None,
    event_bus: EventBus | None = None,
    migrator: TenantSchemaMigrator | None = None,
) -> TenantService:
    """Factory used by routers and Celery tasks."""
    return TenantServiceImpl(
        session,
        audit_service=audit_service,
        event_bus=event_bus,
        migrator=migrator,
    )
