"""Async DB access for tenancy. Internal to the module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.models import Tenant, TenantSettings, TenantSubscription


class TenantRepository:
    """Thin async repository — owns SQL access for tenancy tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(Tenant.id).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        return await self._session.get(Tenant, tenant_id)

    async def insert_tenant(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        name: str,
        contact_email: str,
        schema_name: str,
        legal_name: str | None,
        tax_id: str | None,
        contact_phone: str | None,
        default_locale: str,
        default_unit_system: str,
        actor_user_id: UUID | None,
    ) -> Tenant:
        tenant = Tenant(
            id=tenant_id,
            slug=slug,
            name=name,
            contact_email=contact_email,
            schema_name=schema_name,
            legal_name=legal_name,
            tax_id=tax_id,
            contact_phone=contact_phone,
            default_locale=default_locale,
            default_unit_system=default_unit_system,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def insert_settings(
        self, *, tenant_id: UUID, actor_user_id: UUID | None
    ) -> TenantSettings:
        settings = TenantSettings(
            tenant_id=tenant_id,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(settings)
        await self._session.flush()
        return settings

    async def insert_subscription(
        self,
        *,
        tenant_id: UUID,
        tier: str,
        actor_user_id: UUID | None,
        feature_flags: dict[str, Any] | None = None,
    ) -> TenantSubscription:
        sub = TenantSubscription(
            tenant_id=tenant_id,
            tier=tier,
            started_at=datetime.now(timezone.utc),
            is_current=True,
            feature_flags=feature_flags or {},
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(sub)
        await self._session.flush()
        return sub
