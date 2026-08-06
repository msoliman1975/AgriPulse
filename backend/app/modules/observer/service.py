"""Observer service — tenant scoping, scope resolution, and the stage ribbon.

The ribbon is assembled here rather than in the frontend on purpose. Deciding
that "402 of 402 cell aggregates" is healthy while "118 of 215 trend days" is
not requires knowing which denominators are meaningful, and that knowledge
belongs next to the SQL that produced them. A frontend that re-derived it
would drift the first time a denominator changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.repository import BUCKETS, ObserverRepository
from app.modules.observer.verify_store import VerifyStore
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


class SceneNotFoundError(Exception):
    """No ingestion job with that id in this tenant."""


class SceneRasterUnavailableError(Exception):
    """The scene never produced a raster, so there is nothing to read."""


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
        finally:
            await self._unscope()

        return {
            "farm_id": farm_id,
            "block_count": len(blocks),
            "window_from": window_from,
            "window_to": window_to,
            "stages": _build_stages(jobs, indices, cells, trend, consumers),
            "calc_versions": calc_versions,
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
        """Inputs, resolved grid geometry and asset keys for one scene."""
        await self._scope(tenant_schema)
        try:
            ctx = await self._repo.scene_context(job_id)
            history = (
                await self._repo.scene_calc_history(
                    block_id=ctx["block_id"],
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
        raw_uri = _raw_bands_uri(ctx)
        result = _explain(
            raw_uri=raw_uri,
            band_names=tuple(ctx["bands"]),
            supported_indices=tuple(ctx["supported_indices"]),
            aoi_geojson_utm=json.loads(ctx["boundary_utm_geojson"]),
            lon=lon,
            lat=lat,
            formulas=formulas,
        )
        return {
            "job_id": job_id,
            "scene_id": ctx["scene_id"],
            "scene_datetime": ctx["scene_datetime"],
            "block_id": ctx["block_id"],
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
        )
        return {
            "job_id": job_id,
            "aoi_pixel_count": budget.aoi_pixel_count,
            "masked_pixel_count": budget.masked_pixel_count,
            "per_index": budget.per_index,
            "recomputed_live": True,
        }

    async def _scene_context_and_formulas(
        self, tenant_schema: str, job_id: UUID
    ) -> tuple[dict[str, Any], dict[str, str]]:
        await self._scope(tenant_schema)
        try:
            ctx = await self._repo.scene_context(job_id)
            formulas = await self._repo.index_formulas()
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

    async def scene_indices(
        self,
        *,
        tenant_schema: str,
        block_id: UUID,
        product_id: UUID,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        await self._scope(tenant_schema)
        try:
            return await self._repo.scene_index_rows(
                block_id=block_id, product_id=product_id, scene_time=scene_time
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
    from app.modules.indices.computation import S2_SCL_MASKED_CLASSES

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
        # current ruleset, which is only the truth for freshly-computed rows.
        "mask_ruleset": "s2_scl_v1",
        "mask_classes": list(S2_SCL_MASKED_CLASSES),
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
