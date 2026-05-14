"""Async DB access for tenancy. Internal to the module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEventArchive
from app.modules.tenancy.models import Tenant, TenantSettings, TenantSubscription

_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "legal_name",
        "tax_id",
        "contact_email",
        "contact_phone",
        "default_locale",
        "default_unit_system",
        "default_timezone",
        "default_currency",
        "country_code",
        "logo_url",
        "branding_color",
    }
)


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

    async def list_tenants(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Tenant], int]:
        """Return (rows, total) for the admin list page."""
        base = select(Tenant)
        count_base = select(func.count(Tenant.id))
        if not include_deleted:
            base = base.where(Tenant.deleted_at.is_(None))
            count_base = count_base.where(Tenant.deleted_at.is_(None))
        if status is not None:
            base = base.where(Tenant.status == status)
            count_base = count_base.where(Tenant.status == status)
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(Tenant.slug).like(pattern) | func.lower(Tenant.name).like(pattern)
            )
            count_base = count_base.where(
                func.lower(Tenant.slug).like(pattern) | func.lower(Tenant.name).like(pattern)
            )

        base = base.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)

        rows = (await self._session.execute(base)).scalars().all()
        total = (await self._session.execute(count_base)).scalar_one()
        return list(rows), int(total)

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
        pending_owner_email: str | None = None,
        pending_owner_full_name: str | None = None,
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
            pending_owner_email=pending_owner_email,
            pending_owner_full_name=pending_owner_full_name,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def set_provisioning_state(
        self,
        *,
        tenant: Tenant,
        status: str,
        keycloak_group_id: str | None = None,
        clear_pending_owner: bool = False,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        tenant.status = status
        if keycloak_group_id is not None:
            tenant.keycloak_group_id = keycloak_group_id
        if clear_pending_owner:
            tenant.pending_owner_email = None
            tenant.pending_owner_full_name = None
        tenant.updated_by = actor_user_id
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
            started_at=datetime.now(UTC),
            is_current=True,
            feature_flags=feature_flags or {},
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(sub)
        await self._session.flush()
        return sub

    async def update_profile(
        self,
        *,
        tenant: Tenant,
        patch: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> tuple[Tenant, tuple[str, ...]]:
        """Apply whitelisted profile fields to `tenant`. Returns (tenant, changed)."""
        changed: list[str] = []
        for field, value in patch.items():
            if field not in _UPDATABLE_FIELDS:
                continue
            if getattr(tenant, field) == value:
                continue
            setattr(tenant, field, value)
            changed.append(field)
        if changed:
            tenant.updated_by = actor_user_id
            await self._session.flush()
        return tenant, tuple(changed)

    async def set_status(
        self,
        *,
        tenant: Tenant,
        status: str,
        actor_user_id: UUID | None,
        suspended_at: datetime | None = None,
        deleted_at: datetime | None = None,
        reason: str | None = None,
        clear_suspended_at: bool = False,
        clear_deleted_at: bool = False,
    ) -> Tenant:
        tenant.status = status
        if suspended_at is not None:
            tenant.suspended_at = suspended_at
        if clear_suspended_at:
            tenant.suspended_at = None
        if deleted_at is not None:
            tenant.deleted_at = deleted_at
        if clear_deleted_at:
            tenant.deleted_at = None
        if reason is not None or status == "active":
            tenant.last_status_reason = reason
        tenant.updated_by = actor_user_id
        await self._session.flush()
        return tenant

    async def delete_public_rows(self, tenant_id: UUID) -> None:
        """Delete the tenant's `public.*` rows. Caller already dropped the schema."""
        await self._session.execute(
            delete(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
        )
        await self._session.execute(
            delete(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        await self._session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await self._session.flush()

    # ---- Detail-page sidecar -----------------------------------------------

    async def get_settings(self, tenant_id: UUID) -> TenantSettings | None:
        return await self._session.get(TenantSettings, tenant_id)

    async def get_current_subscription(self, tenant_id: UUID) -> TenantSubscription | None:
        stmt = (
            select(TenantSubscription)
            .where(
                TenantSubscription.tenant_id == tenant_id,
                TenantSubscription.is_current.is_(True),
            )
            .order_by(TenantSubscription.started_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_active_members(self, tenant_id: UUID) -> int:
        # `tenant_memberships` lives in `public` and is owned by the iam
        # module; reach for it via raw SQL to avoid circular imports.
        result = await self._session.execute(
            text(
                "SELECT count(*) FROM public.tenant_memberships "
                "WHERE tenant_id = :tid AND status = 'active'"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tenant_id},
        )
        return int(result.scalar_one())

    async def list_archive_events(
        self, tenant_id: UUID, *, limit: int = 20
    ) -> list[AuditEventArchive]:
        stmt = (
            select(AuditEventArchive)
            .where(AuditEventArchive.subject_id == tenant_id)
            .order_by(AuditEventArchive.occurred_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
