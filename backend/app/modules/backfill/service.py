"""Backfill console service — pickers, estimates, and run dispatch.

Dispatches by Celery task *name* through ``current_app.send_task`` instead
of importing ``app.modules.imagery`` / ``app.modules.weather``. That keeps
this module free of any import edge to the two it drives, and means the API
process does not need the worker's task modules loaded to queue work.

Task names dispatched here (all already live in production since #303):

  imagery.backfill_farm_scenes   raw Sentinel-2 scenes for a farm's subs
  weather.backfill_weather       raw hourly observations from the archive
  imagery.backfill_farm_indices   reproject a farm's stored scenes
  weather.backfill_weather_indices  project stored obs into daily indices
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from celery import current_app as celery_current_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backfill.repository import BackfillRepository

logger = logging.getLogger(__name__)

TASK_IMAGERY_BACKFILL = "imagery.backfill_farm_scenes"
TASK_WEATHER_BACKFILL = "weather.backfill_weather"
TASK_IMAGERY_INDICES = "imagery.backfill_farm_indices"
TASK_WEATHER_INDICES = "weather.backfill_weather_indices"

# Rough per-scene cost used for the pre-flight estimate. CDSE consumption
# is not metered anywhere in the app, so this is an approximation and the
# API says so explicitly (`units_estimated: true`) rather than presenting a
# fabricated number as fact.
_UNITS_PER_SCENE = 1.0
# Clear-scene yield for Sentinel-2 over Egypt: ~5-day revisit, most of it
# usable. Deliberately conservative so the estimate over- rather than
# under-states the spend.
_SCENES_PER_SUB_PER_DAY = 1 / 5.0


class FarmNotFoundError(Exception):
    """Farm does not exist in the given tenant schema."""


class BackfillConflictError(Exception):
    """The farm already has a run in flight."""

    def __init__(self, existing: dict[str, Any]) -> None:
        super().__init__("a backfill run is already in progress for this farm")
        self.existing = existing


class BackfillService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self._repo = BackfillRepository(session)

    # ---- pickers --------------------------------------------------------

    async def list_tenants(self) -> list[dict[str, Any]]:
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT id, name, slug, schema_name
                      FROM public.tenants
                     WHERE status = 'active'
                     ORDER BY name
                    """
                )
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def list_farms(self, tenant_schema: str) -> list[dict[str, Any]]:
        """Farms in one tenant, each flagged if a run already holds it.

        The flag lets the UI disable those options up front rather than
        letting the admin fill in a form that is guaranteed to 409.
        """
        await self._set_search_path(tenant_schema)
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT f.id, f.name, f.code,
                           (SELECT count(*) FROM blocks b
                             WHERE b.farm_id = f.id AND b.deleted_at IS NULL) AS block_count
                      FROM farms f
                     WHERE f.deleted_at IS NULL
                     ORDER BY f.name
                    """
                )
            )
        ).mappings()
        farms = [dict(r) for r in rows]
        await self._reset_search_path()

        for f in farms:
            active = await self._repo.active_for_farm(f["id"])
            f["active_run_id"] = active["id"] if active else None
        return farms

    # ---- estimate -------------------------------------------------------

    async def estimate(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        window_from: date,
        window_to: date,
        imagery: bool,
        weather: bool,
    ) -> dict[str, Any]:
        """Pre-flight scale of a run. No side effects."""
        await self._set_search_path(tenant_schema)
        row = (
            (
                await self._s.execute(
                    text(
                        """
                    SELECT
                      (SELECT count(*) FROM blocks b
                        WHERE b.farm_id = :fid AND b.deleted_at IS NULL) AS blocks,
                      (SELECT count(*) FROM imagery_aoi_subscriptions s
                         JOIN blocks b ON b.id = s.block_id
                        WHERE b.farm_id = :fid
                          AND s.is_active = TRUE
                          AND s.deleted_at IS NULL) AS subscriptions
                    """
                    ),
                    {"fid": str(farm_id)},
                )
            )
            .mappings()
            .one()
        )
        await self._reset_search_path()

        days = max((window_to - window_from).days + 1, 0)
        subs = int(row["subscriptions"])
        scenes = int(round(subs * days * _SCENES_PER_SUB_PER_DAY)) if imagery else 0
        return {
            "days": days,
            "blocks": int(row["blocks"]),
            "subscriptions": subs,
            "estimated_scenes": scenes,
            "estimated_units": round(scenes * _UNITS_PER_SCENE),
            # There is no CDSE metering in the app, so this is an informed
            # approximation, not a quota reading. The UI labels it as such.
            "units_estimated": True,
            "weather_hours": days * 24 if weather else 0,
        }

    # ---- dispatch -------------------------------------------------------

    async def create_run(
        self,
        *,
        tenant_id: UUID,
        tenant_schema: str,
        tenant_name: str | None,
        farm_id: UUID,
        window_from: date,
        window_to: date,
        imagery: bool,
        weather: bool,
        kind: str,
        actor_id: UUID | None,
        actor_email: str | None,
    ) -> dict[str, Any]:
        farm = await self._farm(tenant_schema, farm_id)
        if farm is None:
            raise FarmNotFoundError(str(farm_id))

        existing = await self._repo.active_for_farm(farm_id)
        if existing is not None:
            raise BackfillConflictError(existing)

        run = await self._repo.create(
            tenant_id=tenant_id,
            tenant_schema=tenant_schema,
            tenant_name=tenant_name,
            farm_id=farm_id,
            farm_name=farm.get("name") or farm.get("code"),
            kind=kind,
            sources={"imagery": imagery, "weather": weather},
            window_from=window_from.isoformat(),
            window_to=window_to.isoformat(),
            created_by=actor_id,
            created_by_email=actor_email,
        )
        await self._s.commit()

        # Queue only after the row is committed: the tasks report progress
        # against this id, and a worker can pick one up immediately.
        self._dispatch(
            run_id=run["id"],
            kind=kind,
            farm_id=farm_id,
            tenant_schema=tenant_schema,
            window_from=window_from,
            window_to=window_to,
            imagery=imagery,
            weather=weather,
        )
        return run

    def _dispatch(
        self,
        *,
        run_id: UUID,
        kind: str,
        farm_id: UUID,
        tenant_schema: str,
        window_from: date,
        window_to: date,
        imagery: bool,
        weather: bool,
    ) -> None:
        app = celery_current_app
        rid = str(run_id)
        if kind == "indices":
            if imagery:
                app.send_task(
                    TASK_IMAGERY_INDICES,
                    kwargs={
                        "farm_id": str(farm_id),
                        "tenant_schema": tenant_schema,
                        "from_iso": window_from.isoformat(),
                        "to_iso": window_to.isoformat(),
                        "run_id": rid,
                    },
                    queue="heavy",
                )
            if weather:
                # This task reprojects the last N days rather than taking a
                # window, so translate. Reaching back to `window_from` covers
                # the requested range; the overshoot past `window_to` is
                # harmless because reprojection is idempotent.
                days = max((date.today() - window_from).days + 1, 1)
                app.send_task(
                    TASK_WEATHER_INDICES,
                    kwargs={
                        "farm_id": str(farm_id),
                        "tenant_schema": tenant_schema,
                        "days": days,
                        "run_id": rid,
                    },
                    queue="heavy",
                )
            return

        if imagery:
            app.send_task(
                TASK_IMAGERY_BACKFILL,
                kwargs={
                    "farm_id": str(farm_id),
                    "tenant_schema": tenant_schema,
                    "from_iso": window_from.isoformat(),
                    "to_iso": window_to.isoformat(),
                    "run_compute_indices": False,
                    "run_id": rid,
                },
                queue="heavy",
            )
        if weather:
            app.send_task(
                TASK_WEATHER_BACKFILL,
                kwargs={
                    "farm_id": str(farm_id),
                    "tenant_schema": tenant_schema,
                    "provider_code": "open-meteo",
                    "start_iso": window_from.isoformat(),
                    "end_iso": window_to.isoformat(),
                    "run_id": rid,
                },
                queue="heavy",
            )

    # ---- reads ----------------------------------------------------------

    async def list_runs(
        self, *, tenant_id: UUID | None, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        return await self._repo.list_runs(tenant_id=tenant_id, status=status, limit=limit)

    async def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        return await self._repo.get(run_id)

    # ---- helpers --------------------------------------------------------

    async def _farm(self, tenant_schema: str, farm_id: UUID) -> dict[str, Any] | None:
        await self._set_search_path(tenant_schema)
        row = (
            await self._s.execute(
                text("SELECT id, name, code FROM farms WHERE id = :fid AND deleted_at IS NULL"),
                {"fid": str(farm_id)},
            )
        ).mappings()
        found = row.one_or_none()
        await self._reset_search_path()
        return dict(found) if found else None

    async def _set_search_path(self, tenant_schema: str) -> None:
        # Schema names are generated by `schema_name_for` (tenant_<hex>) and
        # never user-supplied, but validate anyway before interpolating —
        # this is the one place a bind parameter cannot be used.
        if not tenant_schema.startswith("tenant_") or not tenant_schema[7:].isalnum():
            raise ValueError(f"refusing suspicious tenant schema: {tenant_schema!r}")
        await self._s.execute(text(f'SET LOCAL search_path TO "{tenant_schema}", public'))

    async def _reset_search_path(self) -> None:
        await self._s.execute(text("SET LOCAL search_path TO public"))


def get_backfill_service(session: AsyncSession) -> BackfillService:
    return BackfillService(session)
