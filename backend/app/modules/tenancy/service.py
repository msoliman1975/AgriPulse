"""Tenancy service: public Protocol + concrete implementation.

Other modules depend on the `TenantService` Protocol, never on
`TenantServiceImpl`. The concrete impl is wired in
`app.core.app_factory` (or in tests, with stubs).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.tenancy.bootstrap import AlembicTenantMigrator, TenantSchemaMigrator
from app.modules.tenancy.events import (
    TenantCreatedV1,
    TenantDeletionCancelledV1,
    TenantDeletionRequestedV1,
    TenantPurgedV1,
    TenantReactivatedV1,
    TenantSuspendedV1,
    TenantUpdatedV1,
)
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.repository import TenantRepository
from app.shared.auth.tenant_status import invalidate as invalidate_tenant_status_cache
from app.shared.db.ids import schema_name_for, uuid7
from app.shared.eventbus import EventBus, get_default_bus
from app.shared.keycloak import (
    KeycloakAdminClient,
    KeycloakError,
    KeycloakNotConfiguredError,
    get_keycloak_client,
)


# Grace window between request_delete and purge eligibility.
# Aligns with docs/runbooks/tenant-offboarding.md "≥ 30 days".
PURGE_GRACE_DAYS: int = 30


class TenantService(Protocol):
    """Public contract for the tenancy module."""

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        contact_email: str,
        owner_email: str | None = None,
        owner_full_name: str | None = None,
        legal_name: str | None = None,
        tax_id: str | None = None,
        contact_phone: str | None = None,
        default_locale: str = "en",
        default_unit_system: str = "feddan",
        initial_tier: str = "free",
        actor_user_id: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> TenantCreatedResult: ...

    async def retry_provisioning(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def list_tenants(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantListResult: ...

    async def get_tenant(self, tenant_id: UUID) -> TenantSnapshot: ...

    async def get_tenant_sidecar(
        self, tenant_id: UUID, *, audit_limit: int = 20
    ) -> TenantSidecar: ...

    async def update_tenant(
        self,
        tenant_id: UUID,
        *,
        patch: dict[str, Any],
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def suspend_tenant(
        self,
        tenant_id: UUID,
        *,
        reason: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def reactivate_tenant(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def request_delete(
        self,
        tenant_id: UUID,
        *,
        reason: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def cancel_delete(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot: ...

    async def purge_tenant(
        self,
        tenant_id: UUID,
        *,
        slug_confirmation: str,
        force: bool = False,
        actor_user_id: UUID | None = None,
    ) -> None: ...


# ---- DTOs ------------------------------------------------------------------


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
        "provisioning_failed",
        "owner_user_id",
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
        provisioning_failed: bool = False,
        owner_user_id: str | None = None,
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
        self.provisioning_failed = provisioning_failed
        self.owner_user_id = owner_user_id


@dataclass(frozen=True)
class TenantSnapshot:
    """Read-side projection of a Tenant row, returned by lifecycle methods."""

    id: UUID
    slug: str
    name: str
    legal_name: str | None
    tax_id: str | None
    contact_email: str
    contact_phone: str | None
    schema_name: str
    status: str
    default_locale: str
    default_unit_system: str
    default_timezone: str
    default_currency: str
    country_code: str
    suspended_at: datetime | None
    deleted_at: datetime | None
    last_status_reason: str | None
    purge_eligible_at: datetime | None
    keycloak_group_id: str | None
    pending_owner_email: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TenantListResult:
    items: tuple[TenantSnapshot, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class TenantSettingsSnapshot:
    cloud_cover_threshold_visualization_pct: int
    cloud_cover_threshold_analysis_pct: int
    imagery_refresh_cadence_hours: int
    alert_notification_channels: tuple[str, ...]
    webhook_endpoint_url: str | None
    dashboard_default_indices: tuple[str, ...]


@dataclass(frozen=True)
class TenantSubscriptionSnapshot:
    id: UUID
    tier: str
    plan_type: str | None
    started_at: datetime
    expires_at: datetime | None
    is_current: bool
    trial_start: object | None  # datetime.date — kept loose to avoid import churn
    trial_end: object | None
    feature_flags: dict[str, object]


@dataclass(frozen=True)
class ArchiveEventSnapshot:
    id: UUID
    occurred_at: datetime
    event_type: str
    actor_user_id: UUID | None
    actor_kind: str
    details: dict[str, object]
    correlation_id: UUID | None


@dataclass(frozen=True)
class TenantSidecar:
    """Read-only sidecar for the admin detail page."""

    tenant_id: UUID
    settings: TenantSettingsSnapshot | None
    subscription: TenantSubscriptionSnapshot | None
    active_member_count: int
    recent_events: tuple[ArchiveEventSnapshot, ...]


# ---- Errors ----------------------------------------------------------------


class SlugAlreadyExistsError(ValueError):
    """Raised when create_tenant is called with a slug already in use."""


class TenantNotFoundError(LookupError):
    """Raised when the target tenant id does not exist (or is fully purged)."""


class InvalidStatusTransitionError(ValueError):
    """Raised when a lifecycle method is called from an incompatible status."""

    def __init__(self, current: str, attempted: str) -> None:
        super().__init__(
            f"cannot transition tenant from status={current!r} via {attempted!r}"
        )
        self.current = current
        self.attempted = attempted


class SlugConfirmationMismatchError(ValueError):
    """Raised when purge_tenant is called with the wrong slug confirmation."""


class PurgeNotEligibleError(ValueError):
    """Raised when purge_tenant is called before the grace window has elapsed."""

    def __init__(self, eligible_at: datetime) -> None:
        super().__init__(f"tenant not purge-eligible until {eligible_at.isoformat()}")
        self.eligible_at = eligible_at


class NothingToProvisionError(ValueError):
    """Raised when retry_provisioning is called on a tenant with no pending data."""


# ---- Helpers ---------------------------------------------------------------


def _to_snapshot(t: Tenant) -> TenantSnapshot:
    purge_eligible_at: datetime | None = None
    if t.status == "pending_delete" and t.deleted_at is not None:
        purge_eligible_at = t.deleted_at + timedelta(days=PURGE_GRACE_DAYS)
    return TenantSnapshot(
        id=t.id,
        slug=t.slug,
        name=t.name,
        legal_name=t.legal_name,
        tax_id=t.tax_id,
        contact_email=t.contact_email,
        contact_phone=t.contact_phone,
        schema_name=t.schema_name,
        status=t.status,
        default_locale=t.default_locale,
        default_unit_system=t.default_unit_system,
        default_timezone=t.default_timezone,
        default_currency=t.default_currency,
        country_code=t.country_code,
        suspended_at=t.suspended_at,
        deleted_at=t.deleted_at,
        last_status_reason=t.last_status_reason,
        purge_eligible_at=purge_eligible_at,
        keycloak_group_id=t.keycloak_group_id,
        pending_owner_email=t.pending_owner_email,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ---- Implementation --------------------------------------------------------


class TenantServiceImpl:
    """Concrete TenantService — async session injected per call.

    The session is the admin session (search_path = public only). Schema
    bootstrap (CREATE SCHEMA + alembic upgrade) runs *after* the DB
    transaction commits, so a failed insert never leaves an orphan schema.
    A failed bootstrap leaves the tenant row but no schema — recoverable
    via `scripts/migrate_tenants.py`.

    Purge is the inverse: schema drop runs *after* the public-row delete
    commits, so a mid-purge crash leaves an orphan schema (recoverable by
    re-running purge with `force=True` once the public row is reinstated
    or by `DROP SCHEMA` by hand) rather than orphaned public rows.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
        migrator: TenantSchemaMigrator | None = None,
        keycloak_client: KeycloakAdminClient | None = None,
    ) -> None:
        self._session = session
        self._repo = TenantRepository(session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._migrator = migrator or AlembicTenantMigrator()
        self._kc = keycloak_client or get_keycloak_client()
        self._log = get_logger(__name__)

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        contact_email: str,
        owner_email: str | None = None,
        owner_full_name: str | None = None,
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
            pending_owner_email=owner_email,
            pending_owner_full_name=owner_full_name,
        )
        await self._repo.insert_settings(tenant_id=tenant_id, actor_user_id=actor_user_id)
        await self._repo.insert_subscription(
            tenant_id=tenant_id,
            tier=initial_tier,
            actor_user_id=actor_user_id,
        )

        # Flush only — caller's session.begin() context will commit.
        await self._session.flush()

        # Bootstrap the schema (sync DDL + Alembic) off the event loop.
        await asyncio.to_thread(self._migrator.bootstrap, schema_name)

        provisioning_failed = False
        owner_user_id: str | None = None
        if owner_email is not None:
            # Owner provisioning: invite via Keycloak AND materialize the
            # public.users / tenant_memberships / tenant_role_assignments
            # rows so the new owner is a real TenantOwner with caps the
            # moment they sign in. Routed through TenantUsersService for
            # a single invite-user code path shared with the tenant-side
            # users module. The HTTP create-tenant request requires
            # owner_email; service-level callers (tests, scripts) may
            # still create owner-less tenants for narrow scenarios and
            # then call assign_first_owner separately.
            from app.modules.iam.users_service import TenantUsersService

            users_service = TenantUsersService(
                public_session=self._session,
                keycloak=self._kc,
                audit=self._audit,
            )
            try:
                group_id = await self._kc.ensure_group(slug)
            except KeycloakError as exc:
                provisioning_failed = True
                self._log.warning(
                    "tenant_provisioning_failed",
                    tenant_id=str(tenant_id),
                    slug=slug,
                    error=str(exc),
                )
                tenant = await self._repo.set_provisioning_state(
                    tenant=tenant,
                    status="pending_provision",
                    actor_user_id=actor_user_id,
                )
            else:
                owner_result = await users_service.invite_user(
                    email=owner_email,
                    full_name=owner_full_name or owner_email,
                    phone=None,
                    tenant_role="TenantOwner",
                    tenant_schema=schema_name,
                    actor_user_id=actor_user_id,
                )
                owner_user_id = (
                    str(owner_result["user_id"])
                    if owner_result.get("user_id") is not None
                    else None
                )
                if owner_result.get("keycloak_provisioning") == "succeeded":
                    tenant = await self._repo.set_provisioning_state(
                        tenant=tenant,
                        status="active",
                        keycloak_group_id=group_id,
                        clear_pending_owner=True,
                        actor_user_id=actor_user_id,
                    )
                else:
                    # DB rows landed but Keycloak invite couldn't reach
                    # the server (Noop client / transient outage).
                    # Operator follows the kcadm.sh runbook to finish.
                    provisioning_failed = True
                    tenant = await self._repo.set_provisioning_state(
                        tenant=tenant,
                        status="pending_provision",
                        keycloak_group_id=group_id,
                        actor_user_id=actor_user_id,
                    )

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
                "provisioning_failed": provisioning_failed,
            },
            correlation_id=correlation_id,
        )

        self._bus.publish(
            TenantCreatedV1(
                tenant_id=tenant_id,
                slug=slug,
                schema_name=schema_name,
                contact_email=contact_email,
                created_at=tenant.created_at or datetime.now(UTC),
                actor_user_id=actor_user_id,
            )
        )

        invalidate_tenant_status_cache(tenant_id)
        self._log.info(
            "tenant_created",
            tenant_id=str(tenant_id),
            slug=slug,
            schema=schema_name,
            provisioning_failed=provisioning_failed,
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
            created_at=tenant.created_at or datetime.now(UTC),
            provisioning_failed=provisioning_failed,
            owner_user_id=owner_user_id,
        )

    async def retry_provisioning(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status != "pending_provision":
            raise InvalidStatusTransitionError(tenant.status, "retry_provisioning")
        owner_email = tenant.pending_owner_email
        if not owner_email:
            raise NothingToProvisionError(
                "tenant has no pending_owner_email recorded — re-create or "
                "patch the tenant row before retrying"
            )

        try:
            group_id = await self._kc.ensure_group(tenant.slug)
            await self._kc.invite_user(
                email=owner_email,
                full_name=tenant.pending_owner_full_name,
                group_id=group_id,
            )
        except KeycloakNotConfiguredError:
            # Not configured ≠ failed — the operator has not enabled
            # provisioning yet. Surface as a 503-equivalent in the router.
            raise

        tenant = await self._repo.set_provisioning_state(
            tenant=tenant,
            status="active",
            keycloak_group_id=group_id,
            clear_pending_owner=True,
            actor_user_id=actor_user_id,
        )
        await self._audit.record_archive(
            event_type="platform.tenant_provisioning_retried",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={"slug": tenant.slug, "schema_name": tenant.schema_name},
        )
        invalidate_tenant_status_cache(tenant_id)
        self._log.info(
            "tenant_provisioning_retried", tenant_id=str(tenant_id), slug=tenant.slug
        )
        return _to_snapshot(tenant)

    async def list_tenants(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantListResult:
        rows, total = await self._repo.list_tenants(
            status=status,
            search=search,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )
        return TenantListResult(
            items=tuple(_to_snapshot(t) for t in rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_tenant(self, tenant_id: UUID) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        return _to_snapshot(tenant)

    async def get_tenant_sidecar(
        self, tenant_id: UUID, *, audit_limit: int = 20
    ) -> TenantSidecar:
        # Fail fast if the tenant doesn't exist, even if everything else
        # below would still legally return empties.
        await self._require(tenant_id)

        settings = await self._repo.get_settings(tenant_id)
        subscription = await self._repo.get_current_subscription(tenant_id)
        member_count = await self._repo.count_active_members(tenant_id)
        events = await self._repo.list_archive_events(tenant_id, limit=audit_limit)

        return TenantSidecar(
            tenant_id=tenant_id,
            settings=(
                TenantSettingsSnapshot(
                    cloud_cover_threshold_visualization_pct=settings.cloud_cover_threshold_visualization_pct,
                    cloud_cover_threshold_analysis_pct=settings.cloud_cover_threshold_analysis_pct,
                    imagery_refresh_cadence_hours=settings.imagery_refresh_cadence_hours,
                    alert_notification_channels=tuple(settings.alert_notification_channels),
                    webhook_endpoint_url=settings.webhook_endpoint_url,
                    dashboard_default_indices=tuple(settings.dashboard_default_indices),
                )
                if settings is not None
                else None
            ),
            subscription=(
                TenantSubscriptionSnapshot(
                    id=subscription.id,
                    tier=subscription.tier,
                    plan_type=subscription.plan_type,
                    started_at=subscription.started_at,
                    expires_at=subscription.expires_at,
                    is_current=subscription.is_current,
                    trial_start=subscription.trial_start,
                    trial_end=subscription.trial_end,
                    feature_flags=dict(subscription.feature_flags or {}),
                )
                if subscription is not None
                else None
            ),
            active_member_count=member_count,
            recent_events=tuple(
                ArchiveEventSnapshot(
                    id=e.id,
                    occurred_at=e.occurred_at,
                    event_type=e.event_type,
                    actor_user_id=e.actor_user_id,
                    actor_kind=e.actor_kind,
                    details=dict(e.details or {}),
                    correlation_id=e.correlation_id,
                )
                for e in events
            ),
        )

    async def update_tenant(
        self,
        tenant_id: UUID,
        *,
        patch: dict[str, Any],
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status == "pending_delete":
            raise InvalidStatusTransitionError(tenant.status, "update")

        tenant, changed = await self._repo.update_profile(
            tenant=tenant, patch=patch, actor_user_id=actor_user_id
        )
        if changed:
            await self._audit.record_archive(
                event_type="platform.tenant_updated",
                actor_user_id=actor_user_id,
                subject_kind="tenant",
                subject_id=tenant_id,
                details={"slug": tenant.slug, "fields": list(changed)},
            )
            self._bus.publish(
                TenantUpdatedV1(
                    tenant_id=tenant_id,
                    slug=tenant.slug,
                    changed_fields=changed,
                    actor_user_id=actor_user_id,
                )
            )
            self._log.info(
                "tenant_updated", tenant_id=str(tenant_id), fields=list(changed)
            )
        return _to_snapshot(tenant)

    async def suspend_tenant(
        self,
        tenant_id: UUID,
        *,
        reason: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status != "active":
            raise InvalidStatusTransitionError(tenant.status, "suspend")

        when = datetime.now(UTC)
        tenant = await self._repo.set_status(
            tenant=tenant,
            status="suspended",
            suspended_at=when,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        await self._audit.record_archive(
            event_type="platform.tenant_suspended",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={
                "slug": tenant.slug,
                "schema_name": tenant.schema_name,
                "reason": reason,
            },
        )
        self._bus.publish(
            TenantSuspendedV1(
                tenant_id=tenant_id,
                slug=tenant.slug,
                schema_name=tenant.schema_name,
                suspended_at=when,
                reason=reason,
                actor_user_id=actor_user_id,
            )
        )
        invalidate_tenant_status_cache(tenant_id)
        # Best-effort: disable Keycloak users in the tenant group so OIDC
        # also denies. DB-side status block already kicks in via the
        # auth middleware; KC is defense-in-depth.
        try:
            disabled = await self._kc.disable_users_in_group(tenant.slug)
            self._log.info(
                "tenant_keycloak_disabled", tenant_id=str(tenant_id), count=disabled
            )
        except KeycloakError as exc:
            self._log.warning(
                "tenant_keycloak_disable_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

        self._log.info("tenant_suspended", tenant_id=str(tenant_id), reason=reason)
        return _to_snapshot(tenant)

    async def reactivate_tenant(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status != "suspended":
            raise InvalidStatusTransitionError(tenant.status, "reactivate")

        when = datetime.now(UTC)
        tenant = await self._repo.set_status(
            tenant=tenant,
            status="active",
            clear_suspended_at=True,
            reason=None,
            actor_user_id=actor_user_id,
        )
        await self._audit.record_archive(
            event_type="platform.tenant_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={"slug": tenant.slug, "schema_name": tenant.schema_name},
        )
        self._bus.publish(
            TenantReactivatedV1(
                tenant_id=tenant_id,
                slug=tenant.slug,
                schema_name=tenant.schema_name,
                reactivated_at=when,
                actor_user_id=actor_user_id,
            )
        )
        invalidate_tenant_status_cache(tenant_id)
        try:
            enabled = await self._kc.enable_users_in_group(tenant.slug)
            self._log.info(
                "tenant_keycloak_enabled", tenant_id=str(tenant_id), count=enabled
            )
        except KeycloakError as exc:
            self._log.warning(
                "tenant_keycloak_enable_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

        self._log.info("tenant_reactivated", tenant_id=str(tenant_id))
        return _to_snapshot(tenant)

    async def request_delete(
        self,
        tenant_id: UUID,
        *,
        reason: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status not in ("active", "suspended"):
            raise InvalidStatusTransitionError(tenant.status, "request_delete")

        when = datetime.now(UTC)
        tenant = await self._repo.set_status(
            tenant=tenant,
            status="pending_delete",
            deleted_at=when,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        eligible_at = when + timedelta(days=PURGE_GRACE_DAYS)
        await self._audit.record_archive(
            event_type="platform.tenant_deletion_requested",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={
                "slug": tenant.slug,
                "schema_name": tenant.schema_name,
                "reason": reason,
                "purge_eligible_at": eligible_at.isoformat(),
            },
        )
        self._bus.publish(
            TenantDeletionRequestedV1(
                tenant_id=tenant_id,
                slug=tenant.slug,
                schema_name=tenant.schema_name,
                requested_at=when,
                purge_eligible_at=eligible_at,
                reason=reason,
                actor_user_id=actor_user_id,
            )
        )
        invalidate_tenant_status_cache(tenant_id)
        self._log.info("tenant_deletion_requested", tenant_id=str(tenant_id))
        return _to_snapshot(tenant)

    async def cancel_delete(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> TenantSnapshot:
        tenant = await self._require(tenant_id)
        if tenant.status != "pending_delete":
            raise InvalidStatusTransitionError(tenant.status, "cancel_delete")

        when = datetime.now(UTC)
        # Returning to suspended (not active) is the conservative default —
        # whoever cancelled deletion still has to make an explicit "OK to
        # log in" decision via reactivate.
        tenant = await self._repo.set_status(
            tenant=tenant,
            status="suspended",
            suspended_at=when,
            clear_deleted_at=True,
            reason=None,
            actor_user_id=actor_user_id,
        )
        await self._audit.record_archive(
            event_type="platform.tenant_deletion_cancelled",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={"slug": tenant.slug, "schema_name": tenant.schema_name},
        )
        self._bus.publish(
            TenantDeletionCancelledV1(
                tenant_id=tenant_id,
                slug=tenant.slug,
                schema_name=tenant.schema_name,
                cancelled_at=when,
                actor_user_id=actor_user_id,
            )
        )
        invalidate_tenant_status_cache(tenant_id)
        self._log.info("tenant_deletion_cancelled", tenant_id=str(tenant_id))
        return _to_snapshot(tenant)

    async def purge_tenant(
        self,
        tenant_id: UUID,
        *,
        slug_confirmation: str,
        force: bool = False,
        actor_user_id: UUID | None = None,
    ) -> None:
        tenant = await self._require(tenant_id)
        if tenant.status != "pending_delete":
            raise InvalidStatusTransitionError(tenant.status, "purge")
        if slug_confirmation != tenant.slug:
            raise SlugConfirmationMismatchError(
                "slug confirmation does not match tenant slug"
            )

        deleted_at = tenant.deleted_at
        if deleted_at is not None and not force:
            eligible_at = deleted_at + timedelta(days=PURGE_GRACE_DAYS)
            if datetime.now(UTC) < eligible_at:
                raise PurgeNotEligibleError(eligible_at)

        slug = tenant.slug
        schema_name = tenant.schema_name

        # Capture archive event first so the trail survives even if the
        # schema-drop step fails or the process dies.
        when = datetime.now(UTC)
        await self._audit.record_archive(
            event_type="platform.tenant_purged",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={
                "slug": slug,
                "schema_name": schema_name,
                "force": force,
            },
        )

        await self._repo.delete_public_rows(tenant_id)
        await self._session.flush()

        # Schema drop runs after the public-row delete commits — the caller's
        # session.begin() will commit on exit. Drop is sync DDL; offload to thread.
        await asyncio.to_thread(self._migrator.purge, schema_name)

        # Best-effort Keycloak cleanup. Failures here leave orphan groups/
        # users that are easy to delete by hand later via kcadm.sh.
        try:
            removed = await self._kc.delete_users_and_group(slug)
            self._log.info(
                "tenant_keycloak_purged", tenant_id=str(tenant_id), removed=removed
            )
        except KeycloakError as exc:
            self._log.warning(
                "tenant_keycloak_purge_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

        self._bus.publish(
            TenantPurgedV1(
                tenant_id=tenant_id,
                slug=slug,
                schema_name=schema_name,
                purged_at=when,
                actor_user_id=actor_user_id,
            )
        )
        invalidate_tenant_status_cache(tenant_id)
        self._log.info(
            "tenant_purged",
            tenant_id=str(tenant_id),
            slug=slug,
            schema=schema_name,
        )

    async def _require(self, tenant_id: UUID) -> Tenant:
        tenant = await self._repo.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"tenant {tenant_id} not found")
        return tenant


def get_tenant_service(
    session: AsyncSession,
    *,
    audit_service: AuditService | None = None,
    event_bus: EventBus | None = None,
    migrator: TenantSchemaMigrator | None = None,
    keycloak_client: KeycloakAdminClient | None = None,
) -> TenantService:
    """Factory used by routers and Celery tasks."""
    return TenantServiceImpl(
        session,
        audit_service=audit_service,
        event_bus=event_bus,
        migrator=migrator,
        keycloak_client=keycloak_client,
    )
