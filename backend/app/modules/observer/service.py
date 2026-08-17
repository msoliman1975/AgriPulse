"""Observer service — tenant scoping, scope resolution, and the stage ribbon.

The ribbon is assembled here rather than in the frontend on purpose. Deciding
that "402 of 402 cell aggregates" is healthy while "118 of 215 trend days" is
not requires knowing which denominators are meaningful, and that knowledge
belongs next to the SQL that produced them. A frontend that re-derived it
would drift the first time a denominator changed.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.lineage import ObserverLineageRepository
from app.modules.observer.repository import BUCKETS, ObserverRepository
from app.modules.observer.verify_store import VerifyStore
from app.modules.observer.weather import (
    COVERAGE_WARN_HOURS as WEATHER_COVERAGE_WARN_HOURS,
)
from app.modules.observer.weather import ObserverWeatherRepository
from app.shared.storage import get_storage_client

# Widest window the overview will scan in one request. The overview fires
# several aggregates over hypertables; without a ceiling an operator can ask
# for "all of time" across a 36-block farm and wait on a full-table scan.
MAX_WINDOW_DAYS = 750

# Below this share of expected output, a stage is called out rather than
# tinted amber. 0.99 not 1.0: a scene landing between the aggregate write and
# the CAGG refresh is normal, and flagging that would train operators to
# ignore the colour.
_HEALTHY = 0.99


class TenantNotFoundError(Exception):
    """No active tenant with that id."""


class FarmNotFoundError(Exception):
    """Farm does not exist in this tenant schema."""


class DecisionNotFoundError(Exception):
    """No recommendation or alert with that id in this tenant."""


class WeatherDayNotFoundError(Exception):
    """No `weather_index_daily` row for that (farm, index, day)."""


class CellNotFoundError(Exception):
    """No grid cell with that id in this tenant."""


class IndexNotSupportedError(Exception):
    """The scene's product does not offer that index."""


class SceneNotFoundError(Exception):
    """No ingestion job with that id in this tenant."""


class SceneRasterUnavailableError(Exception):
    """The scene never produced a raster, so there is nothing to read."""


class BlockScopedSceneRequiredError(Exception):
    """The operation needs one block, and this scene covers a whole farm.

    Verification and the cell drill-down both compare against `block_*`
    rows keyed on a single block. A farm acquisition has none of its own —
    it produced a row on every block of the farm — so running either
    against it would silently pick a block or return nothing and call it a
    result. Saying which block to open instead is the honest answer.
    """


class WindowTooWideError(Exception):
    """Requested window exceeds MAX_WINDOW_DAYS."""

    def __init__(self, days: int) -> None:
        super().__init__(f"window of {days} days exceeds the {MAX_WINDOW_DAYS}-day limit")
        self.days = days


class ObserverService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self._repo = ObserverRepository(session)
        self._store = VerifyStore(session)
        self._weather = ObserverWeatherRepository(session)
        self._lineage = ObserverLineageRepository(session)

    # ---- tenant plumbing -------------------------------------------------

    async def list_tenants(self) -> list[dict[str, Any]]:
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT id, name, slug, schema_name
                      FROM public.tenants
                     WHERE status = 'active'
                       AND deleted_at IS NULL
                     ORDER BY name
                    """
                )
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def schema_for(self, tenant_id: UUID) -> str:
        row = (
            await self._s.execute(
                text(
                    """
                    SELECT schema_name FROM public.tenants
                     WHERE id = :id AND status = 'active' AND deleted_at IS NULL
                    """
                ),
                {"id": str(tenant_id)},
            )
        ).first()
        if row is None:
            raise TenantNotFoundError(str(tenant_id))
        return str(row[0])

    async def _scope(self, tenant_schema: str) -> None:
        # Schema names come from `schema_name_for` (tenant_<hex>) and are never
        # caller-supplied, but this is the one place a bind parameter cannot be
        # used, so validate before interpolating.
        if not tenant_schema.startswith("tenant_") or not tenant_schema[7:].isalnum():
            raise ValueError(f"refusing suspicious tenant schema: {tenant_schema!r}")
        await self._s.execute(text(f'SET LOCAL search_path TO "{tenant_schema}", public'))

    async def _unscope(self) -> None:
        """Reset search_path, tolerating an already-aborted transaction.

        `_scope`/`_unscope` bracket every read in a try/finally. When the read
        itself fails, the transaction is aborted and this `SET LOCAL` raises
        `InFailedSQLTransactionError` *from the finally block* — which replaces
        the real error with a useless one. The same shape cost us #347/#348.

        Swallowing is safe here specifically because `SET LOCAL` dies with the
        transaction anyway: there is nothing to reset on a connection that is
        about to roll back.
        """
        with contextlib.suppress(SQLAlchemyError):
            await self._s.execute(text("SET LOCAL search_path TO public"))

    # ---- pickers ---------------------------------------------------------

    async def list_farms(self, tenant_schema: str) -> list[dict[str, Any]]:
        await self._scope(tenant_schema)
        try:
            return await self._repo.list_farms()
        finally:
            await self._unscope()

    async def list_products(self, tenant_schema: str, farm_id: UUID) -> list[dict[str, Any]]:
        await self._scope(tenant_schema)
        try:
            return await self._repo.list_products_for_farm(farm_id)
        finally:
            await self._unscope()

    # ---- L0 --------------------------------------------------------------

    async def overview(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        block_ids: list[UUID] | None,
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, Any]:
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            blocks = await self._repo.resolve_block_ids(farm_id=farm_id, block_ids=block_ids)
            if not blocks:
                return _empty_overview(farm_id, window_from, window_to)

            # Spelled out rather than splatted from a dict: mypy cannot check
            # a `**kwargs` unpack against these signatures, and a silent
            # mismatch here would be a wrong number rather than a crash.
            jobs = await self._repo.job_stage_counts(
                farm_id=farm_id,
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
            indices = await self._repo.scenes_with_indices(
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
            cells = await self._repo.cell_aggregate_coverage(
                farm_id=farm_id,
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
            trend = await self._repo.trend_coverage(
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
            consumers = await self._repo.consumer_counts(
                block_ids=blocks, window_from=window_from, window_to=window_to
            )
            calc_versions = await self._repo.calc_versions_present(
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
            # The rows behind any shortfall, so the ribbon can SHOW the
            # cause instead of asserting one and sending the reader to the
            # scene list to look for it.
            problems = await self._repo.stage_problem_scenes(
                farm_id=farm_id,
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
            )
        finally:
            await self._unscope()

        return {
            "farm_id": farm_id,
            "block_count": len(blocks),
            "window_from": window_from,
            "window_to": window_to,
            "stages": _build_stages(jobs, indices, cells, trend, consumers),
            "calc_versions": calc_versions,
            "problems": problems,
            "trend_product_ambiguous": trend["product_ambiguous"],
            # Named so the UI never presents it as proven lineage — the true
            # per-number edge is OBS-8.
            "consumers_are_window_proxy": True,
        }

    async def histogram(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        block_ids: list[UUID] | None,
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        bucket: Literal["day", "week", "month"],
    ) -> list[dict[str, Any]]:
        _check_window(window_from, window_to)
        if bucket not in BUCKETS:
            raise ValueError(f"unsupported bucket: {bucket!r}")
        await self._scope(tenant_schema)
        try:
            blocks = await self._repo.resolve_block_ids(farm_id=farm_id, block_ids=block_ids)
            if not blocks:
                return []
            return await self._repo.scene_histogram(
                farm_id=farm_id,
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
                bucket=bucket,
            )
        finally:
            await self._unscope()

    # ---- L1 --------------------------------------------------------------

    async def list_scenes(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        block_ids: list[UUID] | None,
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        statuses: list[str] | None,
        max_valid_pct: float | None,
        with_error: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            blocks = await self._repo.resolve_block_ids(farm_id=farm_id, block_ids=block_ids)
            if not blocks:
                return []
            rows = await self._repo.list_scenes(
                farm_id=farm_id,
                block_ids=blocks,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
                statuses=statuses,
                max_valid_pct=max_valid_pct,
                with_error=with_error,
                limit=limit,
                offset=offset,
            )
        finally:
            await self._unscope()
        for r in rows:
            r["duration_s"] = float(r["duration_s"]) if r["duration_s"] is not None else None
            # A block with no governing grid at scene time expects no cells.
            # Surfacing that as `0/0` invites reading it as a failure, so the
            # gridded flag carries the distinction explicitly.
            r["gridded"] = int(r["cells_expected"]) > 0
        return rows

    # ---- L2 --------------------------------------------------------------

    async def scene_detail(self, *, tenant_schema: str, job_id: UUID) -> dict[str, Any]:
        """Inputs, resolved grid geometry and asset keys for one scene.

        Accepts a block job id or a farm job id — `scene_context` resolves
        either. A farm acquisition's calc runs are recorded per block (the
        zonal pass still runs block by block), so its history is gathered
        across the farm rather than for one block that does not exist.
        """
        await self._scope(tenant_schema)
        try:
            ctx = await self._repo.scene_context(job_id)
            history = (
                await self._repo.scene_calc_history(
                    block_id=ctx["block_id"],
                    farm_id=ctx["farm_id"] if ctx["block_id"] is None else None,
                    product_id=ctx["product_id"],
                    scene_time=ctx["scene_datetime"],
                )
                if ctx is not None
                else []
            )
        finally:
            await self._unscope()
        if ctx is None:
            raise SceneNotFoundError(str(job_id))
        payload = _scene_detail_payload(ctx)
        payload["calc_runs"] = history
        return payload

    async def explain_pixel(
        self,
        *,
        tenant_schema: str,
        job_id: UUID,
        lon: float,
        lat: float,
    ) -> dict[str, Any]:
        """Read one pixel from the raw COG and show the arithmetic.

        Everything that decides the answer — masking, formulas, the AOI
        test — is borrowed from the pipeline's own code, so this cannot
        describe a calculation the pipeline is not performing.
        """
        # Local import: rasterio pulls GDAL, and only this path needs it.
        from app.modules.observer.pixels import explain_pixel as _explain

        ctx, formulas = await self._scene_context_and_formulas(tenant_schema, job_id)
        air_temp_c = ctx["air_temp_c"]
        raw_uri = _raw_bands_uri(ctx)
        result = _explain(
            raw_uri=raw_uri,
            band_names=tuple(ctx["bands"]),
            supported_indices=tuple(ctx["supported_indices"]),
            aoi_geojson_utm=json.loads(ctx["boundary_utm_geojson"]),
            lon=lon,
            lat=lat,
            formulas=formulas,
            # Decides the mask ruleset and the index set. Without it the
            # inspector read a Landsat QA_PIXEL band with Sentinel-2's SCL
            # rules and offered only the optical indices.
            product_code=ctx["product_code"],
            air_temp_c=air_temp_c,
        )
        return {
            "job_id": job_id,
            "scene_id": ctx["scene_id"],
            "scene_datetime": ctx["scene_datetime"],
            "block_id": ctx["block_id"],
            "scope": ctx["scope"],
            "product_code": ctx["product_code"],
            # The reading CWSI was explained against, so a reader can see
            # which number drove it rather than take the index on faith.
            "air_temp_c": air_temp_c,
            "raw_asset_key": _raw_bands_key(ctx),
            "row": result.row,
            "col": result.col,
            "lon": result.lon,
            "lat": result.lat,
            "inside_aoi": result.inside_aoi,
            "band_values": result.band_values,
            "scl_value": result.scl_value,
            "scl_label": result.scl_label,
            "masked": result.masked,
            "mask_reason": result.mask_reason,
            "indices": result.indices,
            "unavailable_indices": result.unavailable_indices,
            # No SCL band means no cloud masking happened at all, which makes
            # this scene's valid-pixel percentage incomparable to one from a
            # product that does mask. Say so rather than let the two sit in
            # the same column looking alike.
            "masking_available": result.scl_value is not None,
        }

    async def pixel_budget(self, *, tenant_schema: str, job_id: UUID) -> dict[str, Any]:
        """Reconcile AOI footprint → masked → no-data → valid, per index.

        Recomputed from the COG because the database cannot answer it: it
        stores valid and total counts, and nothing that distinguishes a
        cloud-masked pixel from a sensor gap.
        """
        from app.modules.observer.pixels import compute_pixel_budget

        ctx, _ = await self._scene_context_and_formulas(tenant_schema, job_id)
        budget = compute_pixel_budget(
            raw_uri=_raw_bands_uri(ctx),
            band_names=tuple(ctx["bands"]),
            supported_indices=tuple(ctx["supported_indices"]),
            aoi_geojson_utm=json.loads(ctx["boundary_utm_geojson"]),
            product_code=ctx["product_code"],
            air_temp_c=ctx["air_temp_c"],
        )
        return {
            "job_id": job_id,
            "aoi_pixel_count": budget.aoi_pixel_count,
            "masked_pixel_count": budget.masked_pixel_count,
            "per_index": budget.per_index,
            "recomputed_live": True,
        }

    async def _air_temp_at(self, farm_id: UUID, scene_time: datetime) -> float | None:
        """Air temperature at the overpass minute, or None.

        CWSI is a canopy-to-air difference, so explaining it needs the same
        reading the pipeline used. Borrowed from the weather module rather
        than re-derived, for the reason every other borrow in Observer
        exists: a second interpolation would eventually disagree with the
        one that produced the stored numbers.

        Never raises. Weather is the input to one of three thermal indices;
        losing it costs CWSI's explanation, not the whole panel.
        """
        from app.modules.weather.service import get_weather_service

        try:
            return await get_weather_service(tenant_session=self._s).air_temp_at(
                farm_id=farm_id, at=scene_time
            )
        except Exception:  # see docstring; CWSI degrades, the panel does not
            return None

    async def _scene_context_and_formulas(
        self, tenant_schema: str, job_id: UUID
    ) -> tuple[dict[str, Any], dict[str, str]]:
        await self._scope(tenant_schema)
        try:
            ctx = await self._repo.scene_context(job_id)
            formulas = await self._repo.index_formulas()
            # Resolved inside the tenant scope, and only for the product
            # that needs it — every other product ignores the argument.
            if ctx is not None and ctx["product_code"] == "landsat_c2_l2_st":
                ctx["air_temp_c"] = await self._air_temp_at(ctx["farm_id"], ctx["scene_datetime"])
            elif ctx is not None:
                ctx["air_temp_c"] = None
        finally:
            await self._unscope()
        if ctx is None:
            raise SceneNotFoundError(str(job_id))
        if not ctx["stac_item_id"] or ctx["status"] != "succeeded":
            # No raster was ever written, so there is nothing to read. Saying
            # which of the two it is beats a GDAL "file not found".
            raise SceneRasterUnavailableError(
                f"scene status is {ctx['status']!r}; no raw-bands COG exists for it"
            )
        return ctx, formulas

    # ---- L4: forward lineage ---------------------------------------------

    async def index_lineage(
        self,
        *,
        tenant_schema: str,
        block_id: UUID,
        product_id: UUID | None,
        index_code: str,
        window_from: datetime,
        window_to: datetime,
        scene_time: datetime | None,
        limit: int,
    ) -> dict[str, Any]:
        """What this index went on to cause on this block.

        Exact, not a time proxy: every consumer here recorded reading this
        index in its evaluation snapshot, and comes back with the value it
        read. The overview's consumer count remains a proxy — it spans a whole
        farm and every index — and is labelled as one.
        """
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            consumers = await self._lineage.consumers_of_index(
                block_id=block_id,
                index_code=index_code,
                window_from=window_from,
                window_to=window_to,
                limit=limit,
            )
            anomalies: list[dict[str, Any]] = []
            threshold: float | None = None
            effective_threshold: float | None = None
            threshold_source: str | None = None
            if scene_time is not None and product_id is not None:
                cells = await self._lineage.cell_values_for_scene(
                    block_id=block_id,
                    product_id=product_id,
                    index_code=index_code,
                    scene_time=scene_time,
                )
                threshold = await self._lineage.anomaly_threshold(
                    block_id=block_id, product_id=product_id
                )
                anomalies, effective_threshold, threshold_source = _detect_anomalies(
                    cells, threshold
                )
        finally:
            await self._unscope()

        stale = [
            c
            for c in consumers["recommendations"] + consumers["alerts"]
            if c.get("observed_value") is not None
        ]
        return {
            "block_id": block_id,
            "index_code": index_code,
            "window_from": window_from,
            "window_to": window_to,
            "recommendations": consumers["recommendations"],
            "alerts": consumers["alerts"],
            "cell_anomalies": anomalies,
            "anomaly_threshold": effective_threshold,
            # Which tier the threshold came from. The tenant-tier setting is
            # not re-resolved here, so this must not read as the sweep's
            # exact number when it says `module_default`.
            "anomaly_threshold_source": threshold_source,
            # These edges are stored, not inferred from timing — the caller
            # can present them as fact.
            "exact": True,
            "consumer_count": len(stale),
        }

    async def decision_source(
        self,
        *,
        tenant_schema: str,
        kind: Literal["recommendation", "alert"],
        decision_id: UUID,
        index_code: str,
    ) -> dict[str, Any]:
        """Reverse lineage: the stored row behind one decision.

        Returns the frozen snapshot value alongside the aggregate row the
        evaluator would have read. When the two disagree the row was
        recomputed *after* the decision, which means the recommendation now
        rests on a number that no longer exists — and no other surface in the
        product can show that.
        """
        await self._scope(tenant_schema)
        try:
            decision = await self._lineage.decision_snapshot(kind=kind, decision_id=decision_id)
            if decision is None:
                raise DecisionNotFoundError(str(decision_id))
            source = await self._lineage.source_row_for_decision(
                block_id=decision["block_id"],
                index_code=index_code,
                at=decision["created_at"],
            )
        finally:
            await self._unscope()

        observed = _snapshot_value(decision["snapshot"], index_code)
        current = float(source["mean"]) if source and source["mean"] is not None else None
        return {
            "kind": kind,
            "decision_id": decision["id"],
            "block_id": decision["block_id"],
            "cell_id": decision["cell_id"],
            "created_at": decision["created_at"],
            "source_code": decision["source_code"],
            "index_code": index_code,
            "observed_value": observed,
            "source_row": source,
            "current_value": current,
            # None when either side is missing — "cannot tell" is not "agrees".
            "values_agree": (
                None
                if observed is None or current is None
                else abs(observed - current) <= _SNAPSHOT_TOLERANCE
            ),
        }

    # ---- weather lane ----------------------------------------------------

    async def weather_overview(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, Any]:
        """The weather ribbon: fetch → observations → derived → indices.

        Farm-scoped by nature — weather is measured at one centroid, so there
        is no block dimension to narrow by, and pretending otherwise would
        invite an operator to select blocks that change nothing.
        """
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            counts = await self._weather.stage_counts(
                farm_id=farm_id, window_from=window_from, window_to=window_to
            )
            coverage = await self._weather.hour_coverage(
                farm_id=farm_id, window_from=window_from, window_to=window_to
            )
            subscribed = await self._weather.farm_has_weather(farm_id)
        finally:
            await self._unscope()

        thin = [d for d in coverage if int(d["hours"]) < WEATHER_COVERAGE_WARN_HOURS]
        return {
            "farm_id": farm_id,
            "window_from": window_from,
            "window_to": window_to,
            "subscribed": subscribed,
            "stages": _build_weather_stages(counts),
            "coverage": coverage,
            # Days that produced a derived row from too few hours. The number
            # exists, looks authoritative, and was computed from a fraction of
            # the day — and nothing else in the product distinguishes them.
            "thin_days": [d for d in thin if d["has_derived"]],
            "coverage_floor_hours": WEATHER_COVERAGE_WARN_HOURS,
            # There is no coverage floor in the derivation itself; Observer
            # only reports. Said explicitly so the number is not read as a
            # guarantee that thin days were rejected.
            "derivation_enforces_floor": False,
        }

    async def weather_attempts(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        window_from: datetime,
        window_to: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            return await self._weather.recent_attempts(
                farm_id=farm_id,
                window_from=window_from,
                window_to=window_to,
                limit=limit,
            )
        finally:
            await self._unscope()

    async def weather_index_days(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        index_code: str,
        window_from: datetime,
        window_to: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            return await self._weather.index_days(
                farm_id=farm_id,
                index_code=index_code,
                window_from=window_from,
                window_to=window_to,
                limit=limit,
            )
        finally:
            await self._unscope()

    async def explain_weather_day(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        index_code: str,
        day: date,
    ) -> dict[str, Any]:
        """The weather counterpart of the pixel inspector."""
        await self._scope(tenant_schema)
        try:
            found = await self._weather.explain_index_day(
                farm_id=farm_id, index_code=index_code, day=day
            )
        finally:
            await self._unscope()
        if found is None:
            raise WeatherDayNotFoundError(f"{index_code} on {day.isoformat()}")
        return found

    # ---- L3: verify ------------------------------------------------------

    async def verify_scene(
        self,
        *,
        tenant_schema: str,
        job_id: UUID,
        mode: Literal["fast", "full"],
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Recompute one scene from its raster and diff against the store.

        Synchronous: it is one task and the operator is already looking at
        that scene. Anything wider is a named run (`create_verify_run`),
        because a year across 36 blocks is ~2,500 of these.

        Writes only to `observer_verifications`. `block_index_aggregates` is
        never touched — a drift verdict is a signal to open the Backfill
        Console, not a licence to repair.
        """
        from app.modules.observer.verify import verify_scene_fast, verify_scene_full

        started = datetime.now(UTC)
        ctx, _ = await self._scene_context_and_formulas(tenant_schema, job_id)
        if ctx["scope"] != "block":
            raise BlockScopedSceneRequiredError(str(job_id))

        await self._scope(tenant_schema)
        try:
            stored_rows = await self._repo.scene_index_rows(
                block_id=ctx["block_id"],
                product_id=ctx["product_id"],
                scene_time=ctx["scene_datetime"],
            )
            history = await self._repo.scene_calc_history(
                block_id=ctx["block_id"],
                product_id=ctx["product_id"],
                scene_time=ctx["scene_datetime"],
            )
        finally:
            await self._unscope()

        stored = {
            r["index_code"]: {
                "mean": r["mean"],
                "valid_pixel_count": r["valid_pixel_count"],
            }
            for r in stored_rows
        }
        aoi = json.loads(ctx["boundary_utm_geojson"])
        supported = tuple(ctx["supported_indices"])

        if mode == "full":
            result = verify_scene_full(
                product_code=ctx["product_code"],
                air_temp_c=ctx["air_temp_c"],
                raw_uri=_raw_bands_uri(ctx),
                band_names=tuple(ctx["bands"]),
                supported_indices=supported,
                aoi_geojson_utm=aoi,
                stored=stored,
            )
        else:
            result = verify_scene_fast(
                index_uris=_index_uris(ctx),
                aoi_geojson_utm=aoi,
                stored=stored,
            )

        duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        await self._scope(tenant_schema)
        try:
            row = await self._store.insert_verification(
                run_id=run_id,
                job_id=job_id,
                block_id=ctx["block_id"],
                product_id=ctx["product_id"],
                scene_time=ctx["scene_datetime"],
                scene_id=ctx["scene_id"],
                mode=mode,
                verdict=result.verdict,
                per_index=result.per_index,
                # Which build produced the numbers being checked. A drift
                # verdict is far more actionable when it can name the version
                # that wrote them.
                calc_version_stored=history[0]["calc_version"] if history else None,
                error=result.error,
                duration_ms=duration_ms,
            )
        finally:
            await self._unscope()
        return row

    async def create_verify_run(
        self,
        *,
        tenant_schema: str,
        farm_id: UUID,
        block_ids: list[UUID] | None,
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        mode: Literal["fast", "full"],
        created_by_email: str | None,
    ) -> dict[str, Any]:
        _check_window(window_from, window_to)
        await self._scope(tenant_schema)
        try:
            run = await self._store.create_run(
                farm_id=farm_id,
                block_ids=block_ids,
                product_id=product_id,
                window_from=window_from,
                window_to=window_to,
                mode=mode,
                created_by_email=created_by_email,
            )
        finally:
            await self._unscope()
        return run

    async def list_verify_runs(
        self, *, tenant_schema: str, farm_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        await self._scope(tenant_schema)
        try:
            return await self._store.list_runs(farm_id=farm_id, limit=limit)
        finally:
            await self._unscope()

    async def get_verify_run(self, *, tenant_schema: str, run_id: UUID) -> dict[str, Any] | None:
        await self._scope(tenant_schema)
        try:
            return await self._store.get_run(run_id)
        finally:
            await self._unscope()

    async def list_verifications(
        self, *, tenant_schema: str, run_id: UUID, verdict: str | None, limit: int
    ) -> list[dict[str, Any]]:
        await self._scope(tenant_schema)
        try:
            return await self._store.list_verifications(run_id=run_id, verdict=verdict, limit=limit)
        finally:
            await self._unscope()

    async def cancel_verify_run(self, *, tenant_schema: str, run_id: UUID) -> dict[str, Any] | None:
        """Release a stuck run so its farm is free again.

        Ships with the feature, not after it. One run per farm is enforced by
        a partial unique index, so a run that never settles blocks that farm
        for good — and #332 is the standing proof that a run which can hang
        will eventually hang.
        """
        await self._scope(tenant_schema)
        try:
            return await self._store.cancel_run(run_id)
        finally:
            await self._unscope()

    async def pixel_grid(
        self,
        *,
        tenant_schema: str,
        job_id: UUID,
        index_code: str,
        cell_id: UUID | None,
        max_pixels: int,
    ) -> dict[str, Any]:
        """Pixel footprints, cell footprints and the aggregates they roll into.

        The whole pixel -> cell -> block chain in one payload, so the map can
        draw it and the panel can show the arithmetic rather than asserting
        it. Passing `cell_id` narrows the pixels to that cell using the
        pipeline's own cell membership rule.

        On a whole-farm acquisition the chain stops at the pixels: the
        raster covers the farm boundary and is perfectly readable, but a
        grid belongs to a block, so `cells` comes back empty and the block
        roll-up is null. `scope` says which of the two the caller is
        looking at rather than leaving them to infer it from the emptiness.
        """
        from app.modules.observer.pixel_grid import build_pixel_grid

        ctx, _ = await self._scene_context_and_formulas(tenant_schema, job_id)
        if index_code not in ctx["supported_indices"]:
            raise IndexNotSupportedError(index_code)

        # A whole-farm acquisition has pixels — the raster covers the farm
        # boundary — but no cells of its own, because a grid belongs to a
        # block. Refusing the whole call over the cell half left the map
        # blank, and the map is what a pixel is clicked ON: it made the
        # thermal pixel explanation unreachable through the UI even though
        # the endpoint behind it works. Serve the pixels, return no cells,
        # and say which it is.
        is_block = ctx["scope"] == "block"
        if not is_block and cell_id is not None:
            raise BlockScopedSceneRequiredError(str(job_id))

        await self._scope(tenant_schema)
        try:
            cells = (
                await self._repo.cells_for_scene(
                    block_id=ctx["block_id"],
                    product_id=ctx["product_id"],
                    index_code=index_code,
                    scene_time=ctx["scene_datetime"],
                )
                if is_block
                else []
            )
            selected = await self._repo.cell_by_id(cell_id) if cell_id else None
            block_rows = (
                await self._repo.scene_index_rows(
                    block_id=ctx["block_id"],
                    product_id=ctx["product_id"],
                    scene_time=ctx["scene_datetime"],
                )
                if is_block
                else []
            )
        finally:
            await self._unscope()

        if cell_id is not None and selected is None:
            raise CellNotFoundError(str(cell_id))

        grid = build_pixel_grid(
            product_code=ctx["product_code"],
            air_temp_c=ctx["air_temp_c"],
            raw_uri=_raw_bands_uri(ctx),
            band_names=tuple(ctx["bands"]),
            aoi_geojson_utm=json.loads(ctx["boundary_utm_geojson"]),
            index_code=index_code,
            cell_polygon_wkt=selected["geom_wkt"] if selected else None,
            max_pixels=max_pixels,
        )

        block = next((r for r in block_rows if r["index_code"] == index_code), None)
        stored_cell = (
            next((c for c in cells if str(c["cell_id"]) == str(cell_id)), None) if cell_id else None
        )

        return {
            "job_id": job_id,
            "scope": ctx["scope"],
            "block_id": ctx["block_id"],
            "index_code": index_code,
            "scene_datetime": ctx["scene_datetime"],
            "resolution_m": grid.resolution_m,
            "boundary_geojson": json.loads(ctx["boundary_geojson"]),
            "selected_cell_id": cell_id,
            "pixels": [
                {
                    "row": p.row,
                    "col": p.col,
                    "value": p.value,
                    "masked": p.masked,
                    "geometry": p.geometry,
                    "lon": p.lon,
                    "lat": p.lat,
                }
                for p in grid.pixels
            ],
            "cells": [
                {
                    "cell_id": c["cell_id"],
                    "row_idx": c["row_idx"],
                    "col_idx": c["col_idx"],
                    "geometry": json.loads(c["geometry"]),
                    "area_m2": _f(c["area_m2"]),
                    "mean": _f(c["mean"]),
                    "min": _f(c["min"]),
                    "max": _f(c["max"]),
                    "std_dev": _f(c["std_dev"]),
                    "valid_pixel_count": c["valid_pixel_count"],
                    "total_pixel_count": c["total_pixel_count"],
                }
                for c in cells
            ],
            "aoi_pixel_count": grid.aoi_pixel_count,
            "returned_pixel_count": grid.returned_pixel_count,
            "truncated": grid.truncated,
            "recomputed_mean": grid.recomputed_mean,
            "recomputed_valid": grid.recomputed_valid,
            "stored_cell_mean": _f(stored_cell["mean"]) if stored_cell else None,
            "stored_cell_valid": stored_cell["valid_pixel_count"] if stored_cell else None,
            "block_mean": _f(block["mean"]) if block else None,
            "block_valid": block["valid_pixel_count"] if block else None,
            "block_total": block["total_pixel_count"] if block else None,
            # Cells claim a pixel by its CENTRE, the block AOI by footprint
            # touch. Per-cell counts therefore do not sum to the block count,
            # and an operator comparing them needs to know that is by design.
            "cell_membership": "centre",
            "block_membership": "footprint_touch",
        }

    async def scene_indices(
        self,
        *,
        tenant_schema: str,
        block_id: UUID | None,
        product_id: UUID,
        scene_time: datetime,
        farm_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Per-index aggregates behind one scene.

        Takes a block for a block acquisition, a farm for a whole-farm one.
        The farm form returns a row per (block, index) rather than one per
        index — see `farm_scene_index_rows` for why it does not average.
        """
        if block_id is None and farm_id is None:
            raise ValueError("scene_indices needs a block_id or a farm_id")
        await self._scope(tenant_schema)
        try:
            if block_id is not None:
                return await self._repo.scene_index_rows(
                    block_id=block_id, product_id=product_id, scene_time=scene_time
                )
            assert farm_id is not None  # narrowed by the guard above
            return await self._repo.farm_scene_index_rows(
                farm_id=farm_id, product_id=product_id, scene_time=scene_time
            )
        finally:
            await self._unscope()


# ---- ribbon assembly -------------------------------------------------------


def _build_stages(
    jobs: dict[str, int],
    indices: dict[str, int],
    cells: dict[str, int],
    trend: dict[str, Any],
    consumers: dict[str, int],
) -> list[dict[str, Any]]:
    """The ribbon, with each stage's denominator and verdict resolved.

    `expected` is what the previous stage should have handed on, which is not
    always the previous stage's count — the cell stage's denominator is the
    subset of scenes on gridded blocks, and treating ungridded scenes as
    missing output would paint an ordinary farm red.
    """
    discovered = jobs["discovered"]
    acquired = jobs["acquired"]
    computed = indices["scenes"]

    stages: list[dict[str, Any]] = [
        _stage(
            "discovered",
            "Discovered",
            discovered,
            expected=None,
            detail={
                "failed": jobs["failed"],
                "in_flight": jobs["in_flight"],
                "skipped": jobs["skipped"],
            },
        ),
        _stage(
            "acquired",
            "Acquired",
            acquired,
            expected=discovered - jobs["skipped"],
            detail={"failed": jobs["failed"]},
        ),
        _stage(
            "indices",
            "Indices computed",
            computed,
            expected=acquired,
            detail={"aggregate_rows": indices["rows"], "index_codes": indices["index_codes"]},
        ),
        _stage(
            "cells",
            "Cell aggregates",
            cells["produced"],
            expected=cells["expected"],
            detail={
                "note": "denominator counts only scenes whose block had a grid "
                "config governing that scene's time"
            },
        ),
        _stage(
            "trend",
            "Trend coverage",
            trend["trend_days"],
            expected=trend["scene_days"],
            detail={"unit": "block-days", "product_ambiguous": trend["product_ambiguous"]},
        ),
        _stage(
            "consumers",
            "Consumers",
            consumers["alerts"] + consumers["recommendations"],
            expected=None,
            detail={"alerts": consumers["alerts"], "recommendations": consumers["recommendations"]},
        ),
    ]
    return stages


def _stage(
    key: str,
    label: str,
    count: int,
    *,
    expected: int | None,
    detail: dict[str, Any],
) -> dict[str, Any]:
    if expected is None:
        verdict = "info"
        shortfall = None
    elif expected <= 0:
        # Nothing was expected. "0 of 0" is not a failure, and calling it one
        # is how an ungridded farm ends up looking broken.
        verdict = "not_applicable"
        shortfall = 0
    else:
        shortfall = expected - count
        ratio = count / expected
        verdict = "ok" if ratio >= _HEALTHY else ("warn" if ratio >= 0.9 else "bad")
    return {
        "key": key,
        "label": label,
        "count": count,
        "expected": expected,
        "shortfall": shortfall,
        "verdict": verdict,
        "detail": detail,
    }


# ---- scene detail ----------------------------------------------------------


def _raw_bands_key(ctx: dict[str, Any]) -> str:
    """The deterministic object-storage key for this scene's raw COG.

    Built with the pipeline's own key builder rather than string-formatted
    here: the five components and their ordering are what makes ingestion
    idempotent, and a second implementation of that layout would eventually
    point the inspector at a path nothing ever wrote.
    """
    from app.modules.imagery.storage import raw_bands_key

    return raw_bands_key(
        provider_code=ctx["provider_code"],
        product_code=ctx["product_code"],
        scene_id=ctx["scene_id"],
        aoi_hash=ctx["aoi_hash"],
    )


def _raw_bands_uri(ctx: dict[str, Any]) -> str:

    return f"s3://{get_storage_client().bucket}/{_raw_bands_key(ctx)}"


def _index_uris(ctx: dict[str, Any]) -> dict[str, str]:
    """Object-storage URIs for the per-index COGs the pipeline wrote.

    Built with the pipeline's own key builder for the same reason the raw
    path is: a second implementation of the layout eventually points at a
    path nothing ever wrote, and a verify that cannot find its source reports
    `source_missing` — which reads as a data problem rather than as a bug
    here.
    """
    from app.modules.imagery.storage import build_asset_key

    bucket = get_storage_client().bucket
    return {
        code: "s3://{}/{}".format(
            bucket,
            build_asset_key(
                provider_code=ctx["provider_code"],
                product_code=ctx["product_code"],
                scene_id=ctx["scene_id"],
                aoi_hash=ctx["aoi_hash"],
                band_or_index=code,
            ),
        )
        for code in ctx["supported_indices"]
    }


def _scene_detail_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    from app.core.settings import get_settings
    from app.modules.imagery.storage import build_asset_key
    from app.modules.indices.computation import (
        LANDSAT_QA_MASKED_BITS,
        MASK_RULESET,
        PRODUCT_MASK_RULESETS,
        S2_SCL_MASKED_CLASSES,
    )

    has_raster = bool(ctx["stac_item_id"]) and ctx["status"] == "succeeded"
    index_assets = (
        {
            code: build_asset_key(
                provider_code=ctx["provider_code"],
                product_code=ctx["product_code"],
                scene_id=ctx["scene_id"],
                aoi_hash=ctx["aoi_hash"],
                band_or_index=code,
            )
            for code in ctx["supported_indices"]
        }
        if has_raster
        else {}
    )
    settings = get_settings()
    # Which rules actually masked this scene, resolved from its product.
    # Hardcoding the Sentinel-2 pair here told every Landsat thermal scene
    # it had been masked by `s2_scl_v1` against SCL classes — a ruleset that
    # cannot even be applied to a bit-packed QA_PIXEL band. The panel is
    # supposed to be incapable of describing rules the pipeline is not
    # running, and on thermal it was doing exactly that.
    product_code = ctx["product_code"]
    mask_ruleset = PRODUCT_MASK_RULESETS.get(product_code, MASK_RULESET)
    if mask_ruleset == "landsat_qa_pixel_v1":
        # Bits, not classes — a different encoding, so the field is named
        # for what it holds rather than reusing `mask_classes`.
        mask_classes: list[int] = []
        mask_bits: list[int] = list(LANDSAT_QA_MASKED_BITS)
    else:
        mask_classes = list(S2_SCL_MASKED_CLASSES)
        mask_bits = []
    return {
        # The tenant /v1/config endpoint carries these, but it requires a
        # tenant scope and an Observer user has none — so the scene that
        # needs them ships them.
        "tile_server_base_url": settings.tile_server_base_url,
        "s3_bucket": get_storage_client().bucket,
        "job_id": ctx["job_id"],
        "block_id": ctx["block_id"],
        "product_id": ctx["product_id"],
        "block_code": ctx["block_code"],
        "block_name": ctx["block_name"],
        "farm_id": ctx["farm_id"],
        "scene_id": ctx["scene_id"],
        "scene_datetime": ctx["scene_datetime"],
        "status": ctx["status"],
        "stac_item_id": ctx["stac_item_id"],
        "cloud_cover_pct": ctx["cloud_cover_pct"],
        "valid_pixel_pct": ctx["valid_pixel_pct"],
        "error_code": ctx["error_code"],
        "error_message": ctx["error_message"],
        "requested_at": ctx["requested_at"],
        "started_at": ctx["started_at"],
        "completed_at": ctx["completed_at"],
        "provider_code": ctx["provider_code"],
        "provider_name": ctx["provider_name"],
        "product_code": ctx["product_code"],
        "product_name": ctx["product_name"],
        "resolution_m": ctx["resolution_m"],
        "bands": list(ctx["bands"]),
        "supported_indices": list(ctx["supported_indices"]),
        "aoi_hash": ctx["aoi_hash"],
        "boundary_geojson": json.loads(ctx["boundary_geojson"]),
        "area_m2": ctx["area_m2"],
        "raw_asset_key": _raw_bands_key(ctx) if has_raster else None,
        "index_asset_keys": index_assets,
        # Named and versioned so a stored row can be attributed to the rules
        # that produced it. OBS-5 persists this per run; until then it is the
        # current ruleset for this scene's PRODUCT, which is only the truth
        # for freshly-computed rows.
        "mask_ruleset": mask_ruleset,
        "mask_classes": mask_classes,
        "mask_bits": mask_bits,
        # 'block' | 'farm'. A farm acquisition covers every block at once,
        # so `block_id` is null and the grid is not resolvable — the UI
        # needs to know which it is looking at rather than infer it.
        "scope": ctx["scope"],
        "grid": (
            {
                "grid_config_id": ctx["grid_config_id"],
                "cell_size_m": ctx["cell_size_m"],
                "utm_srid": ctx["utm_srid"],
                "cell_count": ctx["cell_count"],
                "effective_from": ctx["effective_from"],
                "effective_to": ctx["effective_to"],
            }
            if ctx["grid_config_id"]
            else None
        ),
    }


def _build_weather_stages(counts: dict[str, Any]) -> list[dict[str, Any]]:
    """The weather ribbon, with denominators that mean something.

    `observations` is denominated by the window's own hour count rather than
    by anything stored: comparing what arrived against what should have is
    the whole point, and a denominator derived from the data could never show
    a gap. Everything downstream is denominated by the stage above it.
    """
    attempts = counts["attempts"]
    observations = counts["observations"]
    derived = counts["derived_days"]
    return [
        _stage(
            "attempts",
            "Fetch attempts",
            attempts,
            expected=None,
            detail={"providers_ok": counts["attempts_ok"]},
        ),
        _stage(
            "attempts_ok",
            "Succeeded",
            counts["attempts_ok"],
            expected=attempts,
            detail={},
        ),
        _stage(
            "observations",
            "Hourly observations",
            observations,
            expected=counts["hours_expected"],
            detail={"unit": "hours"},
        ),
        _stage(
            "derived",
            "Derived daily",
            derived,
            expected=counts["days_expected"],
            detail={},
        ),
        _stage(
            "indices",
            "Index daily",
            counts["index_rows"],
            # One row per (day, index). A derived day that produced fewer
            # index rows than the catalog has codes is a real gap, and
            # denominating by the catalog is what surfaces it.
            expected=derived * counts["catalog_codes"],
            detail={
                "index_codes": counts["index_codes"],
                "catalog_codes": counts["catalog_codes"],
            },
        ),
        _stage(
            "baselines",
            "Baselines",
            counts["baseline_codes"],
            expected=counts["catalog_codes"],
            detail={},
        ),
    ]


# The snapshot froze a string; the aggregate is NUMERIC(7,4). Compare at the
# stored precision — anything tighter would report rounding as disagreement.
_SNAPSHOT_TOLERANCE = 0.0001


def _snapshot_value(snapshot: Any, index_code: str) -> float | None:
    """The value this decision recorded reading for one index.

    Prefers the block aggregate over the per-cell one when a tree read both:
    the block number is the one a reader is looking at when they ask "where
    did this come from".
    """
    if not isinstance(snapshot, dict):
        return None
    values = snapshot.get("values")
    if not isinstance(values, dict):
        return None
    for prefix in (f"indices.{index_code}.", f"grid.{index_code}."):
        for key, raw in values.items():
            if not key.startswith(prefix):
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                # Snapshot values are stringified and not all are numeric
                # (a crop path, a stage name). Skip rather than fail.
                continue
    return None


def _detect_anomalies(
    cells: list[dict[str, Any]], threshold: float | None
) -> tuple[list[dict[str, Any]], float, str]:
    """Flag low-outlier cells using the grid module's own detector.

    Re-implementing the z-score maths here would be a second answer to the
    same question, and the one Observer showed would be the one nobody tested
    against production.

    The threshold is the block override when it has one, otherwise the
    module default. The *tenant-tier* setting is deliberately not re-resolved
    here — that needs a public session and the settings resolver mid-scope —
    so the payload reports which source was used rather than implying the
    sweep's exact number.
    """
    from decimal import Decimal

    from app.modules.grid.anomaly import DEFAULT_K, CellMean, detect_low_outliers, effective_k

    k = effective_k(block_override=threshold, tenant_default=DEFAULT_K)
    source = "block_override" if threshold is not None else "module_default"

    usable = [
        CellMean(
            cell_id=c["cell_id"],
            row_idx=int(c["row_idx"]),
            col_idx=int(c["col_idx"]),
            mean=Decimal(str(c["mean"])),
            centroid_lon=float(c["centroid_lon"]),
            centroid_lat=float(c["centroid_lat"]),
        )
        for c in cells
        if c.get("mean") is not None
    ]
    result = detect_low_outliers(usable, k=k)
    if result is None:
        return [], k, source
    return (
        [
            {
                "cell_id": f.cell_id,
                "mean": f.mean,
                "z": f.z,
                "threshold": k,
                "row_idx": f.row_idx,
                "col_idx": f.col_idx,
            }
            for f in result.flagged
        ],
        k,
        source,
    )


def _f(value: Any) -> float | None:
    """Decimal -> float for JSON. NUMERIC columns arrive as Decimal."""
    return None if value is None else float(value)


def _check_window(window_from: datetime, window_to: datetime) -> None:
    if window_to <= window_from:
        raise ValueError("window_to must be after window_from")
    days = (window_to - window_from) // timedelta(days=1)
    if days > MAX_WINDOW_DAYS:
        raise WindowTooWideError(int(days))


def _empty_overview(farm_id: UUID, window_from: datetime, window_to: datetime) -> dict[str, Any]:
    zero = {"discovered": 0, "acquired": 0, "failed": 0, "in_flight": 0, "skipped": 0}
    return {
        "farm_id": farm_id,
        "block_count": 0,
        "window_from": window_from,
        "window_to": window_to,
        "stages": _build_stages(
            zero,
            {"scenes": 0, "rows": 0, "index_codes": 0},
            {"produced": 0, "expected": 0},
            {"scene_days": 0, "trend_days": 0, "product_ambiguous": False},
            {"alerts": 0, "recommendations": 0},
        ),
        "calc_versions": [],
        "problems": [],
        "trend_product_ambiguous": False,
        "consumers_are_window_proxy": True,
    }


def get_observer_service(session: AsyncSession) -> ObserverService:
    return ObserverService(session)


async def audit_observer_action(
    *,
    tenant_id: UUID,
    tenant_schema: str,
    actor_user_id: UUID | None,
    event_type: str,
    subject_id: UUID | None,
    details: dict[str, Any],
) -> None:
    """Audit a verification action into the tenant's own audit log.

    Only verification is audited. It is the one part of Observer that
    consumes worker time and has a start, an outcome and a cost; a drill-down
    view is indistinguishable from an admin opening a farm page, and a row per
    pixel click would bury the events that matter under noise.

    The event lands in the *tenant's* audit stream rather than a platform-only
    one, so the tenant whose data was recomputed can see that it happened.
    """
    from app.modules.audit import get_audit_service

    del tenant_id
    await get_audit_service().record(
        tenant_schema=tenant_schema,
        event_type=event_type,
        actor_user_id=actor_user_id,
        actor_kind="user" if actor_user_id else "system",
        subject_kind="observer_verification",
        subject_id=subject_id,
        details=details,
    )
