"""CRUD over `platform_defaults` and `tenant_settings_overrides`.

Admin-side service code (PR-Set5) writes here directly; everything
else should use the resolver. Plain SQL by default — the ORM models
exist mostly for type hints + the typed admin paths.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession


class SettingsRepository:
    def __init__(self, *, public_session: AsyncSession) -> None:
        self._public = public_session

    # ---- platform_defaults --------------------------------------------------

    async def list_defaults(self) -> list[dict[str, Any]]:
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT key, value, value_schema, description, category,
                           updated_at, updated_by
                    FROM public.platform_defaults
                    ORDER BY category, key
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def get_default(self, *, key: str) -> dict[str, Any] | None:
        row = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT key, value, value_schema, description, category,
                           updated_at, updated_by
                    FROM public.platform_defaults
                    WHERE key = :key
                    """
                    ),
                    {"key": key},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def update_default_value(
        self,
        *,
        key: str,
        value_json: str,
        actor_user_id: UUID | None,
    ) -> bool:
        """Returns True if a row matched and was updated."""
        result = await self._public.execute(
            text(
                """
                UPDATE public.platform_defaults
                SET value = CAST(:value AS jsonb),
                    updated_at = now(),
                    updated_by = :actor
                WHERE key = :key
                """
            ).bindparams(
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"key": key, "value": value_json, "actor": actor_user_id},
        )
        return (result.rowcount or 0) > 0

    # ---- tenant_settings_overrides -----------------------------------------

    async def list_tenant_overrides(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT key, value, updated_at, updated_by
                    FROM public.tenant_settings_overrides
                    WHERE tenant_id = :tid
                    ORDER BY key
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def get_tenant_override(self, *, tenant_id: UUID, key: str) -> dict[str, Any] | None:
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

    async def upsert_tenant_override(
        self,
        *,
        tenant_id: UUID,
        key: str,
        value_json: str,
        actor_user_id: UUID | None,
    ) -> None:
        await self._public.execute(
            text(
                """
                INSERT INTO public.tenant_settings_overrides
                    (tenant_id, key, value, updated_at, updated_by)
                VALUES
                    (:tid, :key, CAST(:value AS jsonb), now(), :actor)
                ON CONFLICT (tenant_id, key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
                """
            ).bindparams(
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"tid": tenant_id, "key": key, "value": value_json, "actor": actor_user_id},
        )

    async def delete_tenant_override(self, *, tenant_id: UUID, key: str) -> bool:
        result = await self._public.execute(
            text(
                """
                DELETE FROM public.tenant_settings_overrides
                WHERE tenant_id = :tid AND key = :key
                """
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tenant_id, "key": key},
        )
        return (result.rowcount or 0) > 0
