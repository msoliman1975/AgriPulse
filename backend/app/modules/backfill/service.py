"""Backfill console service — pickers, estimates, and run dispatch.

Dispatches by Celery task *name* through ``current_app.send_task`` instead
of importing ``app.modules.imagery`` / ``app.modules.weather``. That keeps
this module free of any import edge to the two it drives, and means the API
process does not need the worker's task modules loaded to queue work.

Task names dispatched here (all already live in production since #303):

  imagery.backfill_farm_scenes   raw Sentinel-2 scenes for a farm's subs
                                 (it decides per subscription whether that
                                 means block AOIs or the whole farm)
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

# Product codes, as literals. This module dispatches by task *name* to avoid
# an import edge to the modules it drives (see the docstring); reaching into
# `imagery` for a constant would undo that for one string.
#
# Thermal is its own console source rather than part of `imagery` because the
# two behave nothing alike: different satellite, cadence, cost and failure
# modes. Folded together, a thermal failure would hide inside the imagery
# counter and the estimate could not show that thermal is free.
THERMAL_PRODUCT_CODES = ["landsat_c2_l2_st"]
SOURCE_IMAGERY = "imagery"
SOURCE_THERMAL = "thermal"

# Rough per-scene cost used for the pre-flight estimate. CDSE consumption
# is not metered anywhere in the app, so this is an approximation and the
# API says so explicitly (`units_estimated: true`) rather than presenting a
# fabricated number as fact.
_UNITS_PER_SCENE = 1.0
# Clear-scene yield for Sentinel-2 over Egypt: ~5-day revisit, most of it
# usable. Deliberately conservative so the estimate over- rather than
# under-states the spend.
_SCENES_PER_SUB_PER_DAY = 1 / 5.0

# Landsat 8 + 9 combined nominal revisit is 8 days. Measured over the
# reference farm the mean gap is shorter (~4 d) because two WRS-2 paths
# overlap it, but that is path-dependent, so the nominal is the honest
# figure for an estimate.
_THERMAL_SCENES_PER_SUB_PER_DAY = 1 / 8.0
# Planetary Computer serves this anonymously and free: no account, no
# metering, no quota to spend. Reporting the Sentinel-2 unit cost here
# would invent a bill that does not exist.
_THERMAL_UNITS_PER_SCENE = 0.0


class FarmNotFoundError(Exception):
    """Farm does not exist in the given tenant schema."""


class BackfillConflictError(Exception):
    """The farm already has a run in flight."""

    def __init__(self, existing: dict[str, Any]) -> None:
        super().__init__("a backfill run is already in progress for this farm")
        self.existing = existing


class NoIntegrationConfigError(Exception):
    """A requested source has no active subscription on this farm.

    Without this guard the run would be accepted, dispatch a task, and do
    nothing — the provider work is driven entirely by the farm's
    subscriptions (block ones, or a whole-farm one once it has cut over), so
    zero of both means zero fetches. That reads as a silent success, which is
    the worst possible outcome for an operator who thinks they just loaded a
    year of history.
    """

    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"no active subscriptions for: {', '.join(missing)}")
        self.missing = missing


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
        thermal: bool = False,
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
                          AND s.deleted_at IS NULL
                          AND s.product_id NOT IN (
                              SELECT id FROM public.imagery_products
                               WHERE code = ANY(:thermal_codes))
                          AND NOT EXISTS (
                              SELECT 1 FROM imagery_farm_subscriptions f
                              WHERE f.farm_id = b.farm_id
                                AND f.product_id = s.product_id
                                AND f.is_active
                                AND f.fetch_farm_aoi
                                AND f.deleted_at IS NULL
                          )) AS subscriptions,
                      (SELECT count(*) FROM imagery_farm_subscriptions f
                        WHERE f.farm_id = :fid
                          AND f.is_active = TRUE
                          AND f.fetch_farm_aoi = TRUE
                          AND f.deleted_at IS NULL
                          AND f.product_id NOT IN (
                              SELECT id FROM public.imagery_products
                               WHERE code = ANY(:thermal_codes))) AS farm_aoi_subscriptions,
                      (SELECT count(*) FROM imagery_farm_subscriptions f
                        WHERE f.farm_id = :fid
                          AND f.is_active = TRUE
                          AND f.fetch_farm_aoi = TRUE
                          AND f.deleted_at IS NULL
                          AND f.product_id IN (
                              SELECT id FROM public.imagery_products
                               WHERE code = ANY(:thermal_codes))) AS thermal_subscriptions
                    """
                    ),
                    {"fid": str(farm_id), "thermal_codes": THERMAL_PRODUCT_CODES},
                )
            )
            .mappings()
            .one()
        )
        providers = await self._weather_providers(tenant_schema, farm_id, already_scoped=True)
        await self._reset_search_path()

        days = max((window_to - window_from).days + 1, 0)
        block_subs = int(row["subscriptions"])
        farm_subs = int(row["farm_aoi_subscriptions"])
        # Weather dispatches one task per provider the farm resolves to, so
        # that list IS the count. Counting block rows instead reported zero —
        # "nothing to fetch" — for a farm whose weather moved to the farm row.
        wx_subs = len(providers)
        # One provider fetch per subscription the run will actually dispatch,
        # whatever its shape. A cut-over farm's whole-farm subscription counts
        # once here where its blocks used to count N times — which is the
        # saving the cutover exists to make, so the estimate has to show it.
        subs = block_subs + farm_subs
        scenes = int(round(subs * days * _SCENES_PER_SUB_PER_DAY)) if imagery else 0
        # Thermal is counted on its own cadence and its own (zero) cost. Rolling
        # it into `estimated_scenes` would have Landsat inherit Sentinel-2's
        # 5-day revisit and a per-scene charge that nobody pays.
        thermal_subs = int(row["thermal_subscriptions"])
        thermal_scenes = (
            int(round(thermal_subs * days * _THERMAL_SCENES_PER_SUB_PER_DAY)) if thermal else 0
        )
        return {
            "days": days,
            "blocks": int(row["blocks"]),
            "subscriptions": subs,
            # Non-zero means the imagery half of this run fetches whole-farm
            # surfaces, so the console can say so rather than reporting a
            # block count that no longer describes what will happen.
            "farm_aoi_subscriptions": farm_subs,
            "estimated_scenes": scenes,
            "estimated_units": round(scenes * _UNITS_PER_SCENE),
            # There is no CDSE metering in the app, so this is an informed
            # approximation, not a quota reading. The UI labels it as such.
            "units_estimated": True,
            "weather_hours": days * 24 if weather else 0,
            # Surfaced so the console can warn *before* submitting: a source
            # with no active subscription would dispatch a task that has
            # nothing to fetch and reads as a silent no-op.
            "weather_subscriptions": wx_subs,
            "weather_providers": providers,
            # Thermal, reported separately throughout. `thermal_units` is 0
            # and stays 0: Planetary Computer serves this free and anonymously,
            # so a non-zero number here would invent a bill.
            "thermal_subscriptions": thermal_subs,
            "estimated_thermal_scenes": thermal_scenes,
            "estimated_thermal_units": round(thermal_scenes * _THERMAL_UNITS_PER_SCENE),
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
        thermal: bool = False,
        actor_id: UUID | None,
        actor_email: str | None,
    ) -> dict[str, Any]:
        farm = await self._farm(tenant_schema, farm_id)
        if farm is None:
            raise FarmNotFoundError(str(farm_id))

        existing = await self._repo.active_for_farm(farm_id)
        if existing is not None:
            raise BackfillConflictError(existing)

        # Validate the farm actually has the integration configs the run
        # needs, BEFORE accepting it. Both providers are driven purely by
        # the farm's active per-block subscriptions, so a source with none
        # would dispatch a task that fetches nothing.
        weather_providers = await self._weather_providers(tenant_schema, farm_id)
        missing: list[str] = []
        if imagery and not await self._has_imagery_subs(
            tenant_schema, farm_id, exclude_products=THERMAL_PRODUCT_CODES
        ):
            missing.append("imagery")
        if weather and not weather_providers:
            missing.append("weather")
        # Checked separately, so "thermal" is named in the error rather than
        # a farm with Sentinel-2 but no thermal subscription passing the
        # imagery check and then fetching nothing.
        if thermal and not await self._has_imagery_subs(
            tenant_schema, farm_id, only_products=THERMAL_PRODUCT_CODES
        ):
            missing.append("thermal")
        if missing:
            raise NoIntegrationConfigError(missing)

        run = await self._repo.create(
            tenant_id=tenant_id,
            tenant_schema=tenant_schema,
            tenant_name=tenant_name,
            farm_id=farm_id,
            farm_name=farm.get("name") or farm.get("code"),
            kind=kind,
            sources={"imagery": imagery, "weather": weather, "thermal": thermal},
            window_from=window_from,
            window_to=window_to,
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
            thermal=thermal,
            weather_providers=weather_providers,
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
        thermal: bool,
        weather_providers: list[str],
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
                        # Named explicitly so an imagery run never silently
                        # recomputes thermal scenes under the imagery counter.
                        "product_codes": None,
                        "progress_source": SOURCE_IMAGERY,
                    },
                    queue="heavy",
                )
            if thermal:
                app.send_task(
                    TASK_IMAGERY_INDICES,
                    kwargs={
                        "farm_id": str(farm_id),
                        "tenant_schema": tenant_schema,
                        "from_iso": window_from.isoformat(),
                        "to_iso": window_to.isoformat(),
                        "run_id": rid,
                        "product_codes": THERMAL_PRODUCT_CODES,
                        "progress_source": SOURCE_THERMAL,
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
                    "product_codes": None,
                    "progress_source": SOURCE_IMAGERY,
                },
                queue="heavy",
            )
        if thermal:
            # A whole-farm thermal acquisition computes its indices inline,
            # exactly as the live path does, so `run_compute_indices` stays
            # False here too — it only governs the block path.
            app.send_task(
                TASK_IMAGERY_BACKFILL,
                kwargs={
                    "farm_id": str(farm_id),
                    "tenant_schema": tenant_schema,
                    "from_iso": window_from.isoformat(),
                    "to_iso": window_to.isoformat(),
                    "run_compute_indices": False,
                    "run_id": rid,
                    "product_codes": THERMAL_PRODUCT_CODES,
                    "progress_source": SOURCE_THERMAL,
                },
                queue="heavy",
            )
        if weather:
            # One task per provider the farm is actually subscribed to.
            # NEVER hardcode a provider_code here: the worker's
            # `_make_provider` raises on anything it does not recognise
            # (it matches "open_meteo", underscore), so a guessed literal
            # fails the whole run at execution time.
            for code in weather_providers:
                app.send_task(
                    TASK_WEATHER_BACKFILL,
                    kwargs={
                        "farm_id": str(farm_id),
                        "tenant_schema": tenant_schema,
                        "provider_code": code,
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

    async def cancel_run(self, *, run_id: UUID, actor_email: str | None) -> dict[str, Any] | None:
        """Release a stuck run. None when it was already terminal."""
        row = await self._repo.cancel(
            run_id, reason=f"cancelled by {actor_email or 'platform admin'}"
        )
        if row is not None:
            await self._s.commit()
        return row

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

    async def _weather_providers(
        self, tenant_schema: str, farm_id: UUID, *, already_scoped: bool = False
    ) -> list[str]:
        """Distinct provider codes this farm actually subscribes to.

        Mirrors how the beat sweep resolves them
        (`WeatherRepository.list_due_farm_providers`): the FARM rows are
        authoritative, with the per-block rows as a fallback for any
        (farm, provider) pair that has no farm row yet. Reading only the block
        rows — as this did — misses a farm whose block subscriptions were
        deactivated after 0077 collapsed them, and reports it as having no
        weather integration at all.

        Returning [] means the farm really has none.
        """
        if not already_scoped:
            await self._set_search_path(tenant_schema)
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT f.provider_code
                      FROM weather_farm_subscriptions f
                     WHERE f.farm_id = :fid
                       AND f.is_active = TRUE
                       AND f.deleted_at IS NULL

                     UNION

                    SELECT s.provider_code
                      FROM weather_subscriptions s
                      JOIN blocks b ON b.id = s.block_id
                     WHERE b.farm_id = :fid
                       AND s.is_active = TRUE
                       AND s.deleted_at IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM weather_farm_subscriptions f2
                            WHERE f2.farm_id = b.farm_id
                              AND f2.provider_code = s.provider_code
                              AND f2.is_active
                              AND f2.deleted_at IS NULL
                       )
                     ORDER BY 1
                    """
                ),
                {"fid": str(farm_id)},
            )
        ).all()
        if not already_scoped:
            await self._reset_search_path()
        return [r[0] for r in rows]

    async def _has_imagery_subs(
        self,
        tenant_schema: str,
        farm_id: UUID,
        *,
        only_products: list[str] | None = None,
        exclude_products: list[str] | None = None,
    ) -> bool:
        """Is there anything for this source to fetch — in either shape?

        A farm cut over to whole-farm fetching may have had its block
        subscriptions deactivated, so asking only about those would reject the
        run as unconfigured on exactly the farms the cutover is furthest along
        on.

        The two product filters keep the console's sources honest. Without
        them a farm subscribed to Sentinel-2 but not thermal would pass the
        thermal pre-flight, dispatch a task, fetch nothing, and report a
        green run — the silent-success failure this guard exists to prevent,
        just relocated to a different source.
        """
        product_sql = ""
        params: dict[str, Any] = {"fid": str(farm_id)}
        if only_products is not None:
            product_sql = (
                " AND {alias}.product_id IN"
                " (SELECT id FROM public.imagery_products WHERE code = ANY(:codes))"
            )
            params["codes"] = only_products
        elif exclude_products is not None:
            product_sql = (
                " AND {alias}.product_id NOT IN"
                " (SELECT id FROM public.imagery_products WHERE code = ANY(:codes))"
            )
            params["codes"] = exclude_products

        await self._set_search_path(tenant_schema)
        row = (
            await self._s.execute(
                text(
                    f"""
                    SELECT EXISTS (
                        SELECT 1 FROM imagery_aoi_subscriptions s
                          JOIN blocks b ON b.id = s.block_id
                         WHERE b.farm_id = :fid
                           AND s.is_active = TRUE
                           AND s.deleted_at IS NULL
                           {product_sql.format(alias="s")}
                    ) OR EXISTS (
                        SELECT 1 FROM imagery_farm_subscriptions f
                         WHERE f.farm_id = :fid
                           AND f.is_active = TRUE
                           AND f.fetch_farm_aoi = TRUE
                           AND f.deleted_at IS NULL
                           {product_sql.format(alias="f")}
                    ) AS present
                    """  # noqa: S608 - product_sql is a literal; codes are bound
                ),
                params,
            )
        ).one()
        await self._reset_search_path()
        return bool(row[0])

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
