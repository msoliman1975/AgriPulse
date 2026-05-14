"""Tenant integrations config service.

Two responsibilities:

1. Read resolved values for the four integration categories at any
   tier (tenant / Farm / LandUnit) by chaining the SettingsResolver.
2. Write tenant-tier overrides via SettingsRepository, Farm-tier
   overrides via the new tenant-schema tables (PR-Set4 migration), and
   LandUnit-tier overrides via the existing imagery_aoi_subscriptions
   table.

The resolver bypass for "delete to inherit" is intentional: the user
sees a toggle "Inherit from {parent tier}" → we delete the row. Next
read goes through the resolver and falls through.

Audit on every write — `integrations.tenant_setting_set`,
`integrations.farm_weather_set`, etc.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import AuditService, get_audit_service
from app.shared.settings import (
    ResolvedSetting,
    SettingsRepository,
    SettingsResolver,
)

WEATHER_KEYS = (
    "weather.default_provider_code",
    "weather.default_cadence_hours",
    "weather.forecast_retention_days",
)
IMAGERY_KEYS = (
    "imagery.default_product_code",
    "imagery.cloud_cover_threshold_pct",
)
EMAIL_KEYS = (
    "email.from_address",
    "email.smtp_host",
)
WEBHOOK_KEYS = (
    "webhook.signing_alg",
    "webhook.timeout_seconds",
)


def _resolved_dict(key: str, resolved: ResolvedSetting) -> dict[str, Any]:
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "overridden_at": resolved.overridden_at,
    }


class IntegrationsService:
    def __init__(
        self,
        *,
        public_session: AsyncSession,
        tenant_session: AsyncSession,
        audit: AuditService | None = None,
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session
        self._repo = SettingsRepository(public_session=public_session)
        self._resolver = SettingsResolver(
            public_session=public_session, tenant_session=tenant_session
        )
        self._audit = audit or get_audit_service()

    # ---- Tenant tier reads -------------------------------------------------

    async def list_tenant(self, *, tenant_id: UUID, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in keys:
            resolved = await self._resolver.get_tenant(tenant_id, key)
            out.append(_resolved_dict(key, resolved))
        return out

    # ---- Tenant tier writes -----------------------------------------------

    async def upsert_tenant_value(
        self,
        *,
        tenant_id: UUID,
        key: str,
        value: Any,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        await self._repo.upsert_tenant_override(
            tenant_id=tenant_id,
            key=key,
            value_json=json.dumps(value),
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="integrations.tenant_setting_set",
            actor_user_id=actor_user_id,
            subject_kind="setting",
            subject_id=None,
            farm_id=None,
            details={"key": key, "value": value},
        )
        resolved = await self._resolver.get_tenant(tenant_id, key)
        return _resolved_dict(key, resolved)

    async def delete_tenant_value(
        self,
        *,
        tenant_id: UUID,
        key: str,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        deleted = await self._repo.delete_tenant_override(tenant_id=tenant_id, key=key)
        if deleted:
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type="integrations.tenant_setting_cleared",
                actor_user_id=actor_user_id,
                subject_kind="setting",
                subject_id=None,
                farm_id=None,
                details={"key": key},
            )
        resolved = await self._resolver.get_tenant(tenant_id, key)
        return _resolved_dict(key, resolved)

    # ---- Farm-weather tier ------------------------------------------------

    async def get_farm_weather(self, *, tenant_id: UUID, farm_id: UUID) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in WEATHER_KEYS:
            resolved = await self._resolver.get_farm_weather(tenant_id, farm_id, key)
            out.append(_resolved_dict(key, resolved))
        return out

    async def upsert_farm_weather(
        self,
        *,
        tenant_id: UUID,
        farm_id: UUID,
        provider_code: str | None,
        cadence_hours: int | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> list[dict[str, Any]]:
        # All-NULL upsert == "delete row" (inherit). Not strictly
        # necessary — the resolver falls through on NULL columns
        # already — but a clean DELETE is easier for operators
        # reading the audit log.
        if provider_code is None and cadence_hours is None:
            await self._tenant.execute(
                text("DELETE FROM farm_weather_overrides WHERE farm_id = :fid").bindparams(
                    bindparam("fid", type_=PG_UUID(as_uuid=True))
                ),
                {"fid": farm_id},
            )
        else:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO farm_weather_overrides
                        (farm_id, provider_code, cadence_hours,
                         updated_at, updated_by)
                    VALUES (:fid, :pc, :ch, now(), :actor)
                    ON CONFLICT (farm_id) DO UPDATE SET
                        provider_code = EXCLUDED.provider_code,
                        cadence_hours = EXCLUDED.cadence_hours,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                    """
                ).bindparams(
                    bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "fid": farm_id,
                    "pc": provider_code,
                    "ch": cadence_hours,
                    "actor": actor_user_id,
                },
            )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="integrations.farm_weather_set",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={
                "provider_code": provider_code,
                "cadence_hours": cadence_hours,
            },
        )
        return await self.get_farm_weather(tenant_id=tenant_id, farm_id=farm_id)

    # ---- Farm-imagery tier ------------------------------------------------

    async def get_farm_imagery(self, *, tenant_id: UUID, farm_id: UUID) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in IMAGERY_KEYS:
            resolved = await self._resolver.get_landunit_imagery(
                tenant_id, block_id=farm_id, farm_id=farm_id, key=key
            )
            # `get_landunit_imagery` short-circuits the block tier when
            # block_id == farm_id (no rows match) — leaves Farm tier as
            # the lower bound, which is what we want here.
            out.append(_resolved_dict(key, resolved))
        return out

    async def upsert_farm_imagery(
        self,
        *,
        tenant_id: UUID,
        farm_id: UUID,
        product_code: str | None,
        cloud_cover_threshold_pct: int | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> list[dict[str, Any]]:
        if product_code is None and cloud_cover_threshold_pct is None:
            await self._tenant.execute(
                text("DELETE FROM farm_imagery_overrides WHERE farm_id = :fid").bindparams(
                    bindparam("fid", type_=PG_UUID(as_uuid=True))
                ),
                {"fid": farm_id},
            )
        else:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO farm_imagery_overrides
                        (farm_id, product_code, cloud_cover_threshold_pct,
                         updated_at, updated_by)
                    VALUES (:fid, :pc, :cc, now(), :actor)
                    ON CONFLICT (farm_id) DO UPDATE SET
                        product_code = EXCLUDED.product_code,
                        cloud_cover_threshold_pct = EXCLUDED.cloud_cover_threshold_pct,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                    """
                ).bindparams(
                    bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "fid": farm_id,
                    "pc": product_code,
                    "cc": cloud_cover_threshold_pct,
                    "actor": actor_user_id,
                },
            )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="integrations.farm_imagery_set",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={
                "product_code": product_code,
                "cloud_cover_threshold_pct": cloud_cover_threshold_pct,
            },
        )
        return await self.get_farm_imagery(tenant_id=tenant_id, farm_id=farm_id)

    # ---- LandUnit imagery tier --------------------------------------------

    async def upsert_block_imagery(
        self,
        *,
        block_id: UUID,
        cloud_cover_max_pct: int | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        # Update every active subscription on this block. There can be
        # more than one product code per block; the user is editing the
        # cloud-cover cap which applies uniformly.
        await self._tenant.execute(
            text(
                """
                UPDATE imagery_aoi_subscriptions
                SET cloud_cover_max_pct = :cc,
                    updated_at = now()
                WHERE block_id = :bid AND is_active = TRUE
                """
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id, "cc": cloud_cover_max_pct},
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="integrations.block_imagery_set",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=None,
            details={"cloud_cover_max_pct": cloud_cover_max_pct},
        )
        return {"block_id": block_id, "cloud_cover_max_pct": cloud_cover_max_pct}

    async def apply_to_blocks(
        self,
        *,
        farm_id: UUID,
        mode: str,  # "inherit" | "lock"
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        if mode == "inherit":
            # Reset every per-block override under this farm to NULL so
            # they inherit from Farm/tenant/platform.
            result = await self._tenant.execute(
                text(
                    """
                    UPDATE imagery_aoi_subscriptions ias
                    SET cloud_cover_max_pct = NULL,
                        updated_at = now()
                    FROM blocks b
                    WHERE ias.block_id = b.id
                      AND b.farm_id = :fid
                      AND ias.is_active = TRUE
                    """
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id},
            )
            affected = cast("CursorResult[Any]", result).rowcount or 0
        elif mode == "lock":
            # Write the Farm's resolved cloud-cover into every block.
            farm_settings = await self.get_farm_imagery(tenant_id=UUID(int=0), farm_id=farm_id)
            farm_cloud = next(
                (
                    s["value"]
                    for s in farm_settings
                    if s["key"] == "imagery.cloud_cover_threshold_pct"
                ),
                None,
            )
            if farm_cloud is None:
                affected = 0
            else:
                result = await self._tenant.execute(
                    text(
                        """
                        UPDATE imagery_aoi_subscriptions ias
                        SET cloud_cover_max_pct = :cc,
                            updated_at = now()
                        FROM blocks b
                        WHERE ias.block_id = b.id
                          AND b.farm_id = :fid
                          AND ias.is_active = TRUE
                        """
                    ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                    {"fid": farm_id, "cc": int(farm_cloud)},
                )
                affected = cast("CursorResult[Any]", result).rowcount or 0
        else:
            raise ValueError(f"Unknown apply-to-blocks mode: {mode!r}")
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type=f"integrations.farm_imagery_apply_{mode}",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={"mode": mode, "blocks_affected": affected},
        )
        return {"mode": mode, "blocks_affected": affected}


def get_integrations_service(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession,
) -> IntegrationsService:
    return IntegrationsService(public_session=public_session, tenant_session=tenant_session)
