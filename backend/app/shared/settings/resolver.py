"""Three-tier settings resolver.

Resolution chain for a tenant-tier key:

    platform_defaults  →  tenant_settings_overrides[tenant_id]

For Farm- and LandUnit-tier keys, the lower tiers (`farm_weather_overrides`,
`farm_imagery_overrides`, `imagery_aoi_subscriptions`) are layered ON
TOP of the tenant-tier resolution. PR-Set4 wires up those tables; the
methods in this file already cover the chain — pass `tenant_session`
to enable the lower tiers.

Caching:
* `platform_defaults` is cached in-process for 60s. Same trade-off as
  `app/shared/auth/tenant_status.py` — flips can take up to a minute
  to take effect on a given replica.
* Tenant overrides are read fresh; row count per tenant is tiny.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.settings.errors import SettingNotFoundError

_DEFAULTS_TTL_SECONDS: float = 60.0

Source = Literal["platform", "tenant", "farm", "resource"]


@dataclass(frozen=True)
class ResolvedSetting:
    value: Any
    source: Source
    overridden_at: datetime | None


class _DefaultsCache:
    """Process-wide cache of `platform_defaults` rows. Keyed by `key`."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._loaded_at: float = 0.0

    def is_fresh(self) -> bool:
        return bool(self._rows) and (time.monotonic() - self._loaded_at) < _DEFAULTS_TTL_SECONDS

    def replace(self, rows: list[dict[str, Any]]) -> None:
        self._rows = {r["key"]: r for r in rows}
        self._loaded_at = time.monotonic()

    def get(self, key: str) -> dict[str, Any] | None:
        return self._rows.get(key)

    def invalidate(self) -> None:
        self._rows = {}
        self._loaded_at = 0.0


_cache = _DefaultsCache()


def invalidate_defaults_cache() -> None:
    """Test hook + admin-write hook so flips don't have to wait 60s."""
    _cache.invalidate()


class SettingsResolver:
    """Lookup-only API. Service-side writes go through SettingsRepository.

    The resolver takes both the public session (always required) and an
    optional tenant_session. Pass the tenant session for Farm/LandUnit
    tiers; tenant-only resolutions don't need it.
    """

    def __init__(
        self,
        *,
        public_session: AsyncSession,
        tenant_session: AsyncSession | None = None,
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session

    # ---- Tenant tier --------------------------------------------------------

    async def get_tenant(self, tenant_id: UUID, key: str) -> ResolvedSetting:
        """Resolve a key at the tenant tier. Falls back to platform default."""
        await self._ensure_defaults_cached()
        default = _cache.get(key)
        if default is None:
            raise SettingNotFoundError(key)

        override = await self._fetch_tenant_override(tenant_id=tenant_id, key=key)
        if override is not None:
            return ResolvedSetting(
                value=override["value"],
                source="tenant",
                overridden_at=override["updated_at"],
            )
        return ResolvedSetting(
            value=default["value"],
            source="platform",
            overridden_at=default["updated_at"],
        )

    # ---- Farm tier (weather) -----------------------------------------------

    async def get_farm_weather(
        self,
        tenant_id: UUID,
        farm_id: UUID,
        key: str,
    ) -> ResolvedSetting:
        """Resolve a weather setting for one Farm.

        Chain:
            farm_weather_overrides.<col>
              → tenant_settings_overrides[key]
              → platform_defaults[key]
        """
        column = _farm_weather_column_for(key)
        if self._tenant is not None and column is not None:
            farm_value = await self._fetch_farm_weather_override(farm_id=farm_id, column=column)
            if farm_value is not None:
                value, updated_at = farm_value
                return ResolvedSetting(value=value, source="farm", overridden_at=updated_at)
        return await self.get_tenant(tenant_id, key)

    # ---- LandUnit tier (imagery) -------------------------------------------

    async def get_landunit_imagery(
        self,
        tenant_id: UUID,
        block_id: UUID,
        farm_id: UUID,
        key: str,
    ) -> ResolvedSetting:
        """Resolve an imagery setting for one LandUnit (block).

        Chain:
            imagery_aoi_subscriptions.<col>     (per-block)
              → farm_imagery_overrides.<col>    (Farm-tier)
              → tenant_settings_overrides[key]
              → platform_defaults[key]
        """
        column = _imagery_column_for(key)
        if self._tenant is not None and column is not None:
            block_value = await self._fetch_block_imagery_override(block_id=block_id, column=column)
            if block_value is not None:
                value, updated_at = block_value
                return ResolvedSetting(value=value, source="resource", overridden_at=updated_at)
            farm_value = await self._fetch_farm_imagery_override(farm_id=farm_id, column=column)
            if farm_value is not None:
                value, updated_at = farm_value
                return ResolvedSetting(value=value, source="farm", overridden_at=updated_at)
        return await self.get_tenant(tenant_id, key)

    # ---- Cache plumbing ----------------------------------------------------

    async def _ensure_defaults_cached(self) -> None:
        if _cache.is_fresh():
            return
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT key, value, value_schema, description, category,
                           updated_at, updated_by
                    FROM public.platform_defaults
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        _cache.replace([dict(r) for r in rows])

    # ---- Lookups -----------------------------------------------------------

    async def _fetch_tenant_override(self, *, tenant_id: UUID, key: str) -> dict[str, Any] | None:
        row = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT key, value, updated_at, updated_by
                    FROM public.tenant_settings_overrides
                    WHERE tenant_id = :tid AND key = :key
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": tenant_id, "key": key},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def _fetch_farm_weather_override(
        self, *, farm_id: UUID, column: str
    ) -> tuple[Any, datetime] | None:
        if self._tenant is None:
            return None
        sql = text(
            f"SELECT {column} AS value, updated_at "  # noqa: S608
            "FROM farm_weather_overrides WHERE farm_id = :fid"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True)))
        try:
            row = (await self._tenant.execute(sql, {"fid": farm_id})).mappings().first()
        except Exception:  # table doesn't exist yet (pre-Set4 migration)
            return None
        if row is None or row["value"] is None:
            return None
        return row["value"], row["updated_at"]

    async def _fetch_farm_imagery_override(
        self, *, farm_id: UUID, column: str
    ) -> tuple[Any, datetime] | None:
        if self._tenant is None:
            return None
        sql = text(
            f"SELECT {column} AS value, updated_at "  # noqa: S608
            "FROM farm_imagery_overrides WHERE farm_id = :fid"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True)))
        try:
            row = (await self._tenant.execute(sql, {"fid": farm_id})).mappings().first()
        except Exception:
            return None
        if row is None or row["value"] is None:
            return None
        return row["value"], row["updated_at"]

    async def _fetch_block_imagery_override(
        self, *, block_id: UUID, column: str
    ) -> tuple[Any, datetime] | None:
        # imagery_aoi_subscriptions exists since migration 0003 — no
        # try/except needed. Take the most-recently-updated active row.
        if self._tenant is None:
            return None
        sql = text(
            f"SELECT {column} AS value, "  # noqa: S608
            "       COALESCE(updated_at, created_at) AS updated_at "
            "FROM imagery_aoi_subscriptions "
            "WHERE block_id = :bid AND is_active = TRUE "
            "ORDER BY COALESCE(updated_at, created_at) DESC "
            "LIMIT 1"
        ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True)))
        try:
            row = (await self._tenant.execute(sql, {"bid": block_id})).mappings().first()
        except Exception:
            return None
        if row is None or row["value"] is None:
            return None
        return row["value"], row["updated_at"]


# ---- Key → column mappings -------------------------------------------------
#
# Map the abstract setting key to the concrete column on each lower tier
# table. None means "no per-resource override for this key" — the
# resolver falls straight through to tenant + platform tiers.

_FARM_WEATHER_COLUMNS: dict[str, str] = {
    "weather.default_provider_code": "provider_code",
    "weather.default_cadence_hours": "cadence_hours",
}

_IMAGERY_COLUMNS: dict[str, str] = {
    "imagery.default_product_code": "product_code",
    "imagery.cloud_cover_threshold_pct": "cloud_cover_threshold_pct",
}


def _farm_weather_column_for(key: str) -> str | None:
    return _FARM_WEATHER_COLUMNS.get(key)


def _imagery_column_for(key: str) -> str | None:
    return _IMAGERY_COLUMNS.get(key)
