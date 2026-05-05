"""Celery tasks for the imagery ingestion pipeline.

Three tasks form a chain per scene; a fourth is the Beat-driven sweep:

    discover_scenes(subscription_id, tenant_schema)
        Calls the provider's catalog API, inserts a `pending`
        ingestion job per new scene (idempotent via UNIQUE
        (subscription_id, scene_id)). Skips scenes whose cloud cover
        exceeds the visualization threshold.

    acquire_scene(job_id, tenant_schema)
        Fetches the multi-band COG from the provider, uploads it to
        S3 at the deterministic key, transitions the job to running.

    register_stac_item(job_id, tenant_schema)
        Auto-creates the per-tenant STAC collection on first run,
        upserts the STAC item, transitions the job to succeeded.

    discover_active_subscriptions()
        Beat-only sweep: walks every tenant, finds subscriptions whose
        last attempt is older than their cadence, enqueues
        `discover_scenes` for each.

Each task wraps an async core in `asyncio.run` (Celery workers are
sync). Errors emit `IngestionFailedV1`, audit, and set `status='failed'`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.audit import get_audit_service
from app.modules.imagery.errors import (
    IngestionJobNotFoundError,
    SentinelHubNotConfiguredError,
)
from app.modules.imagery.events import (
    IndexAggregatedV1,
    IngestionFailedV1,
    SceneDiscoveredV1,
    SceneIngestedV1,
    SceneSkippedV1,
)
from app.modules.imagery.pgstac import (
    build_item_doc,
    collection_id_for,
    ensure_collection,
    upsert_item,
)
from app.modules.imagery.providers.protocol import ImageryProvider
from app.modules.imagery.providers.sentinel_hub import SentinelHubProvider
from app.modules.imagery.repository import ImageryRepository
from app.modules.imagery.storage import raw_bands_key
from app.shared.db.ids import uuid7
from app.shared.db.session import AsyncSessionLocal, dispose_engine, sanitize_tenant_schema
from app.shared.eventbus import get_default_bus
from app.shared.storage import StorageClient, get_storage_client

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Wrap a task body's `asyncio.run` so the global async engine is
    disposed after each task.

    Each Celery task creates a fresh event loop via `asyncio.run`. Our
    async engine is a module-level singleton; without disposal between
    tasks, asyncpg connections retained by the pool reference the
    previous (now-closed) loop, and the next task's pool checkout fails
    with `RuntimeError: Event loop is closed` → AttributeError on the
    proactor's `send`. Disposing at the end of each task forces the
    next one to rebuild the pool inside its own loop.

    Engine creation is cheap (asyncpg lazily connects), so per-task
    disposal is acceptable for our workload size. A per-worker engine
    bound to a long-lived loop would be the next-step optimisation.
    """

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


# --- DI seams (overridable in tests) ---------------------------------------


def _make_provider() -> ImageryProvider:
    """Construct the provider for this task invocation.

    SentinelHubProvider raises SentinelHubNotConfiguredError when the
    creds are empty. Tests inject a fake via `set_provider_factory`.
    """
    return SentinelHubProvider()


_provider_factory: Callable[[], ImageryProvider] = _make_provider


def set_provider_factory(factory: Callable[[], ImageryProvider]) -> None:
    """Test seam: swap in a mock ImageryProvider builder."""
    global _provider_factory
    _provider_factory = factory


def reset_provider_factory() -> None:
    global _provider_factory
    _provider_factory = _make_provider


def _get_storage() -> StorageClient:
    return get_storage_client()


# --- Helpers ----------------------------------------------------------------


async def _set_tenant_context(session: AsyncSession, tenant_schema: str) -> None:
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )
    await session.execute(
        text("SELECT set_config('app.tenant_collection_prefix', :v, TRUE)"),
        {"v": f"{safe}__%"},
    )


async def _lookup_product(session: AsyncSession, product_id: UUID) -> dict[str, Any]:
    """Read product code + bands from public.imagery_products."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, code, bands, "
                    "(SELECT code FROM public.imagery_providers p "
                    " WHERE p.id = pr.provider_id) AS provider_code "
                    "FROM public.imagery_products pr WHERE id = :id"
                ),
                {"id": product_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _record_audit(
    *,
    tenant_schema: str,
    event_type: str,
    subject_id: UUID,
    farm_id: UUID | None,
    details: dict[str, Any],
) -> None:
    """Audit envelope used by all imagery state transitions.

    Celery tasks are `system` actors — there's no `actor_user_id` on a
    Beat-driven discovery. The audit service lowers `actor_kind` to
    `system` automatically when `actor_user_id` is None.
    """
    audit = get_audit_service()
    await audit.record(
        tenant_schema=tenant_schema,
        event_type=event_type,
        actor_user_id=None,
        actor_kind="system",
        subject_kind="ingestion_job",
        subject_id=subject_id,
        farm_id=farm_id,
        details=details,
    )


# --- discover_scenes --------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.discover_scenes",
    bind=False,
    ignore_result=True,
)
def discover_scenes(subscription_id: str, tenant_schema: str) -> dict[str, int]:
    """Beat- or refresh-driven entry point for one subscription."""
    return _run_task(_discover_scenes_async(UUID(subscription_id), tenant_schema))


async def _discover_scenes_async(subscription_id: UUID, tenant_schema: str) -> dict[str, int]:
    settings = get_settings()
    bus = get_default_bus()

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)

        subscription = await repo.get_subscription(subscription_id)
        block = await repo.get_block_boundary(subscription["block_id"])
        if block is None:
            _log.warning(
                "imagery_discover_block_missing",
                subscription_id=str(subscription_id),
                block_id=str(subscription["block_id"]),
            )
            return {"discovered": 0, "queued": 0, "skipped_cloud": 0}

        product = await _lookup_product(session, subscription["product_id"])

        # Window: from `last_successful_ingest_at` (or 90 days ago, the
        # retention floor per ARCH §9) up to now.
        now = datetime.now(UTC)
        window_start = subscription["last_successful_ingest_at"] or _ninety_days_ago(now)

        cloud_cap = (
            subscription["cloud_cover_max_pct"]
            if subscription["cloud_cover_max_pct"] is not None
            else settings.imagery_cloud_cover_visualization_max_pct
        )

        # SentinelHubProvider raises SentinelHubNotConfiguredError from
        # its constructor when credentials are empty, so the factory
        # call must live inside the try/except — otherwise the task
        # dies before the synthetic failed-job marker is written and the
        # UI shows nothing.
        provider: ImageryProvider | None = None
        try:
            try:
                provider = _provider_factory()
                scenes = await provider.discover(
                    aoi_geojson=block["boundary_geojson"],
                    product_code=product["code"],
                    from_datetime=window_start,
                    to_datetime=now,
                    max_cloud_cover_pct=cloud_cap,
                )
            except SentinelHubNotConfiguredError:
                # Configuration failure — record one synthetic failed
                # job so dev clusters surface the misconfig loudly.
                marker_id = uuid7()
                await session.execute(
                    text(
                        """
                        INSERT INTO imagery_ingestion_jobs (
                            id, subscription_id, block_id, product_id,
                            scene_id, scene_datetime, status, error_message,
                            requested_at, completed_at
                        ) VALUES (
                            :id, :sub, :block, :prod,
                            :scene, :sdt, 'failed', :err, now(), now()
                        )
                        ON CONFLICT (subscription_id, scene_id) DO NOTHING
                        """
                    ),
                    {
                        "id": marker_id,
                        "sub": subscription_id,
                        "block": subscription["block_id"],
                        "prod": subscription["product_id"],
                        "scene": "__not_configured__",
                        "sdt": now,
                        "err": "sentinel_hub_not_configured",
                    },
                )
                await repo.touch_subscription_attempt(
                    subscription_id=subscription_id, attempted_at=now, success=False
                )
                bus.publish(
                    IngestionFailedV1(job_id=marker_id, error="sentinel_hub_not_configured")
                )
                await _record_audit(
                    tenant_schema=tenant_schema,
                    event_type="imagery.ingestion_failed",
                    subject_id=marker_id,
                    farm_id=block["farm_id"],
                    details={"reason": "sentinel_hub_not_configured"},
                )
                return {"discovered": 0, "queued": 0, "skipped_cloud": 0}
        finally:
            # Provider holds an httpx client; close it eagerly so each
            # task call is hermetic.
            if provider is not None and hasattr(provider, "aclose"):
                await provider.aclose()

        # Insert pending jobs for new scenes; mark over-cap scenes as
        # skipped_cloud (post-insert, so the audit trail records them).
        queued = 0
        skipped_cloud = 0
        for scene in scenes:
            job_id = uuid7()
            new_id, created = await repo.upsert_pending_ingestion_job(
                job_id=job_id,
                subscription_id=subscription_id,
                block_id=subscription["block_id"],
                product_id=subscription["product_id"],
                scene_id=scene.scene_id,
                scene_datetime=scene.scene_datetime,
                cloud_cover_pct=scene.cloud_cover_pct,
            )
            if not created:
                continue  # idempotent re-discovery
            bus.publish(
                SceneDiscoveredV1(
                    job_id=new_id,
                    subscription_id=subscription_id,
                    block_id=subscription["block_id"],
                    scene_id=scene.scene_id,
                    scene_datetime=scene.scene_datetime,
                    cloud_cover_pct=scene.cloud_cover_pct,
                )
            )
            await _record_audit(
                tenant_schema=tenant_schema,
                event_type="imagery.scene_discovered",
                subject_id=new_id,
                farm_id=block["farm_id"],
                details={
                    "scene_id": scene.scene_id,
                    "cloud_cover_pct": (
                        str(scene.cloud_cover_pct) if scene.cloud_cover_pct is not None else None
                    ),
                },
            )

            if (
                scene.cloud_cover_pct is not None
                and scene.cloud_cover_pct > settings.imagery_cloud_cover_visualization_max_pct
            ):
                await repo.mark_skipped(job_id=new_id, completed_at=now, reason="cloud")
                bus.publish(SceneSkippedV1(job_id=new_id, reason="cloud"))
                await _record_audit(
                    tenant_schema=tenant_schema,
                    event_type="imagery.scene_skipped",
                    subject_id=new_id,
                    farm_id=block["farm_id"],
                    details={"reason": "cloud"},
                )
                skipped_cloud += 1
            else:
                queued += 1

        await repo.touch_subscription_attempt(
            subscription_id=subscription_id, attempted_at=now, success=True
        )

    # Enqueue acquisition for every queued job. We do this OUTSIDE the
    # session block so the row is visible to the worker that picks it up.
    if queued:
        # Re-query for queued jobs whose status is still 'pending'.
        async with AsyncSessionLocal()() as session2, session2.begin():
            await _set_tenant_context(session2, tenant_schema)
            rows = (
                await session2.execute(
                    text(
                        "SELECT id FROM imagery_ingestion_jobs "
                        "WHERE subscription_id = :s AND status = 'pending'"
                    ),
                    {"s": subscription_id},
                )
            ).all()
        for (job_id,) in rows:
            acquire_scene.delay(str(job_id), tenant_schema)

    return {
        "discovered": len(scenes),
        "queued": queued,
        "skipped_cloud": skipped_cloud,
    }


# --- acquire_scene ----------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.acquire_scene",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def acquire_scene(job_id: str, tenant_schema: str) -> dict[str, Any]:
    return _run_task(_acquire_scene_async(UUID(job_id), tenant_schema))


async def _acquire_scene_async(job_id: UUID, tenant_schema: str) -> dict[str, Any]:
    bus = get_default_bus()
    storage = _get_storage()
    factory = AsyncSessionLocal()

    # Step 1: read job + transition to running.
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        job = await repo.get_ingestion_job(job_id)
        if job["status"] != "pending":
            # Re-running an already-acquired job is a no-op. The chain
            # naturally short-circuits: register_stac_item only acts on
            # 'running' state.
            return {"job_id": str(job_id), "status": job["status"], "noop": True}
        block = await repo.get_block_boundary(job["block_id"])
        if block is None:
            await repo.mark_failed(
                job_id=job_id,
                completed_at=datetime.now(UTC),
                error_message="block_missing",
            )
            bus.publish(IngestionFailedV1(job_id=job_id, error="block_missing"))
            return {"job_id": str(job_id), "status": "failed"}
        product = await _lookup_product(session, job["product_id"])
        await repo.mark_running(job_id=job_id, started_at=datetime.now(UTC))

    # Step 2: fetch from the provider.
    provider = _provider_factory()
    try:
        try:
            result = await provider.fetch(
                scene_id=job["scene_id"],
                product_code=product["code"],
                aoi_geojson_utm36n=block["boundary_utm_geojson"],
                bands=tuple(product["bands"]),
            )
        except Exception as exc:
            await _fail_job(
                tenant_schema=tenant_schema,
                job_id=job_id,
                farm_id=block["farm_id"],
                error=str(exc) or exc.__class__.__name__,
            )
            return {"job_id": str(job_id), "status": "failed"}
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()

    # Step 3: write the COG to S3 at the deterministic key.
    s3_key = raw_bands_key(
        provider_code=product["provider_code"],
        product_code=product["code"],
        scene_id=job["scene_id"],
        aoi_hash=block["aoi_hash"],
    )
    try:
        storage.put_object(
            key=s3_key,
            body=result.cog_bytes,
            content_type=result.content_type,
        )
    except Exception as exc:
        await _fail_job(
            tenant_schema=tenant_schema,
            job_id=job_id,
            farm_id=block["farm_id"],
            error=f"s3_put_failed: {exc}",
        )
        return {"job_id": str(job_id), "status": "failed"}

    # Step 4: chain register_stac_item with the assets we just wrote.
    register_stac_item.delay(str(job_id), tenant_schema, [s3_key])
    return {"job_id": str(job_id), "status": "running", "asset_key": s3_key}


# --- register_stac_item -----------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.register_stac_item",
    bind=False,
    ignore_result=True,
)
def register_stac_item(
    job_id: str, tenant_schema: str, assets_written: list[str]
) -> dict[str, Any]:
    return _run_task(_register_stac_item_async(UUID(job_id), tenant_schema, assets_written))


async def _register_stac_item_async(
    job_id: UUID,
    tenant_schema: str,
    assets_written: list[str],
) -> dict[str, Any]:
    bus = get_default_bus()
    settings = get_settings()
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        try:
            job = await repo.get_ingestion_job(job_id)
        except IngestionJobNotFoundError:
            return {"job_id": str(job_id), "status": "missing"}
        if job["status"] != "running":
            return {"job_id": str(job_id), "status": job["status"], "noop": True}

        block = await repo.get_block_boundary(job["block_id"])
        if block is None:
            await repo.mark_failed(
                job_id=job_id,
                completed_at=datetime.now(UTC),
                error_message="block_missing",
            )
            bus.publish(IngestionFailedV1(job_id=job_id, error="block_missing"))
            return {"job_id": str(job_id), "status": "failed"}
        product = await _lookup_product(session, job["product_id"])

        try:
            collection_id = collection_id_for(tenant_schema, product["code"])
            await ensure_collection(
                session,
                collection_id=collection_id,
                product_code=product["code"],
            )

            item_id = (
                f"{product['provider_code']}/{product['code']}/"
                f"{job['scene_id']}/{block['aoi_hash']}"
            )
            assets = {
                "raw_bands": {
                    "href": f"s3://{settings.s3_bucket_uploads}/{assets_written[0]}",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                    "bands": list(product["bands"]),
                }
            }
            bbox = _bbox_from_geojson(block["boundary_geojson"])
            item_doc = build_item_doc(
                collection_id=collection_id,
                item_id=item_id,
                geometry_geojson=block["boundary_geojson"],
                bbox=bbox,
                scene_datetime_iso=_iso(job["scene_datetime"]),
                assets=assets,
                properties={
                    "eo:cloud_cover": (
                        float(job["cloud_cover_pct"])
                        if job["cloud_cover_pct"] is not None
                        else None
                    ),
                    "missionagre:scene_id": job["scene_id"],
                    "missionagre:aoi_hash": block["aoi_hash"],
                },
            )
            await upsert_item(session, item_doc=item_doc)
        except Exception as exc:
            await repo.mark_failed(
                job_id=job_id,
                completed_at=datetime.now(UTC),
                error_message=f"stac_register_failed: {exc}",
            )
            bus.publish(IngestionFailedV1(job_id=job_id, error=str(exc)))
            await _record_audit(
                tenant_schema=tenant_schema,
                event_type="imagery.ingestion_failed",
                subject_id=job_id,
                farm_id=block["farm_id"],
                details={"reason": "stac_register_failed", "error": str(exc)},
            )
            return {"job_id": str(job_id), "status": "failed"}

        await repo.mark_succeeded(
            job_id=job_id,
            completed_at=datetime.now(UTC),
            stac_item_id=item_id,
            assets_written=assets_written,
        )

    bus.publish(
        SceneIngestedV1(
            job_id=job_id,
            block_id=job["block_id"],
            scene_id=job["scene_id"],
            stac_item_id=item_id,
        )
    )
    await _record_audit(
        tenant_schema=tenant_schema,
        event_type="imagery.scene_ingested",
        subject_id=job_id,
        farm_id=block["farm_id"],
        details={"stac_item_id": item_id},
    )

    # Chain compute_indices — runs on the heavy queue (rasterio reads
    # are CPU + IO heavy). Failure here doesn't roll back the
    # registration; the job stays `succeeded` and a separate retry
    # tool can re-trigger compute on demand (P2).
    compute_indices.delay(str(job_id), tenant_schema, assets_written[0])

    return {"job_id": str(job_id), "status": "succeeded", "stac_item_id": item_id}


# --- compute_indices --------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.compute_indices",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def compute_indices(job_id: str, tenant_schema: str, raw_bands_key_str: str) -> dict[str, Any]:
    return _run_task(_compute_indices_async(UUID(job_id), tenant_schema, raw_bands_key_str))


async def _compute_indices_async(
    job_id: UUID,
    tenant_schema: str,
    raw_bands_key_str: str,
) -> dict[str, Any]:
    """Read raw_bands COG, compute six indices, write per-index COGs + aggregates.

    All IO routes through the same DI seams as `acquire_scene` so unit
    tests can swap the storage backend. The rasterio reader / writer
    is local to this task — keeps the import graph thin for processes
    that don't need rasterio (the API + light worker).
    """
    bus = get_default_bus()
    storage = _get_storage()

    # Step 1: load job + block + product context.
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        try:
            job = await repo.get_ingestion_job(job_id)
        except IngestionJobNotFoundError:
            return {"job_id": str(job_id), "status": "missing"}
        if job["status"] != "succeeded" or job["stac_item_id"] is None:
            return {"job_id": str(job_id), "status": job["status"], "noop": True}
        block = await repo.get_block_boundary(job["block_id"])
        if block is None:
            return {"job_id": str(job_id), "status": "block_missing"}
        product = await _lookup_product(session, job["product_id"])

    # Step 2: read raw COG, compute indices, write per-index COGs.
    # Local import — pulls rasterio/numpy only into the heavy worker.
    from app.modules.imagery._rasterio_io import (
        compute_and_write_indices,
        load_raw_bands_and_aggregate,
    )

    bucket = storage.bucket
    raw_uri = f"s3://{bucket}/{raw_bands_key_str}"
    try:
        bands_arrays, aoi_mask, profile = load_raw_bands_and_aggregate(
            raw_uri,
            band_names=tuple(product["bands"]),
            aoi_geojson_utm36n=block["boundary_utm_geojson"],
        )
        index_aggregates, index_keys = compute_and_write_indices(
            bands_arrays=bands_arrays,
            aoi_mask=aoi_mask,
            profile=profile,
            storage=storage,
            provider_code=product["provider_code"],
            product_code=product["code"],
            scene_id=job["scene_id"],
            aoi_hash=block["aoi_hash"],
        )
    except Exception as exc:
        bus.publish(IngestionFailedV1(job_id=job_id, error=f"compute_indices_failed: {exc}"))
        await _record_audit(
            tenant_schema=tenant_schema,
            event_type="imagery.ingestion_failed",
            subject_id=job_id,
            farm_id=block["farm_id"],
            details={"reason": "compute_indices_failed", "error": str(exc)},
        )
        return {"job_id": str(job_id), "status": "compute_failed"}

    # Step 3: insert one block_index_aggregates row per index; refresh
    # the pgstac item with merged assets.
    from app.modules.indices.service import get_indices_service

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        indices_service = get_indices_service(tenant_session=session)
        for index_code, agg in index_aggregates.items():
            await indices_service.record_aggregate_row(
                time=job["scene_datetime"],
                block_id=job["block_id"],
                index_code=index_code,
                product_id=job["product_id"],
                stac_item_id=job["stac_item_id"],
                mean=agg.mean,
                min_value=agg.min,
                max_value=agg.max,
                p10=agg.p10,
                p50=agg.p50,
                p90=agg.p90,
                std_dev=agg.std_dev,
                valid_pixel_count=agg.valid_pixel_count,
                total_pixel_count=agg.total_pixel_count,
                cloud_cover_pct=job["cloud_cover_pct"],
            )

        # Refresh pgstac.items with the merged asset map.
        from app.modules.imagery.pgstac import (
            build_item_doc,
            collection_id_for,
            upsert_item,
        )

        collection_id = collection_id_for(tenant_schema, product["code"])
        merged_assets = {
            "raw_bands": {
                "href": f"s3://{bucket}/{raw_bands_key_str}",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "bands": list(product["bands"]),
            },
        }
        for index_code, key in index_keys.items():
            merged_assets[index_code] = {
                "href": f"s3://{bucket}/{key}",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data", "index"],
                "title": index_code.upper(),
            }
        bbox = _bbox_from_geojson(block["boundary_geojson"])
        item_doc = build_item_doc(
            collection_id=collection_id,
            item_id=job["stac_item_id"],
            geometry_geojson=block["boundary_geojson"],
            bbox=bbox,
            scene_datetime_iso=_iso(job["scene_datetime"]),
            assets=merged_assets,
            properties={
                "eo:cloud_cover": (
                    float(job["cloud_cover_pct"]) if job["cloud_cover_pct"] is not None else None
                ),
                "missionagre:scene_id": job["scene_id"],
                "missionagre:aoi_hash": block["aoi_hash"],
            },
        )
        await upsert_item(session, item_doc=item_doc)

    # Step 4: emit one IndexAggregatedV1 per index, audit the batch.
    for index_code, agg in index_aggregates.items():
        bus.publish(
            IndexAggregatedV1(
                block_id=job["block_id"],
                index_code=index_code,
                time=job["scene_datetime"],
                valid_pixel_pct=_valid_pct(agg),
            )
        )
    await _record_audit(
        tenant_schema=tenant_schema,
        event_type="imagery.indices_computed",
        subject_id=job_id,
        farm_id=block["farm_id"],
        details={
            "stac_item_id": job["stac_item_id"],
            "indices": list(index_aggregates.keys()),
        },
    )
    return {
        "job_id": str(job_id),
        "status": "indices_computed",
        "indices": list(index_aggregates.keys()),
    }


def _valid_pct(agg: Any) -> Decimal | None:
    if agg.total_pixel_count == 0:
        return None
    pct = Decimal(agg.valid_pixel_count) * Decimal(100) / Decimal(agg.total_pixel_count)
    return pct.quantize(Decimal("0.01"))


# --- discover_active_subscriptions (Beat sweep) -----------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.discover_active_subscriptions",
    bind=False,
    ignore_result=True,
)
def discover_active_subscriptions() -> dict[str, int]:
    return _run_task(_discover_active_subscriptions_async())


async def _discover_active_subscriptions_async() -> dict[str, int]:
    factory = AsyncSessionLocal()

    # Step 1: list active tenants from public.tenants.
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    tenant_schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for tenant_schema in tenant_schemas:
        try:
            sanitize_tenant_schema(tenant_schema)
        except ValueError:
            continue
        async with AsyncSessionLocal()() as session2, session2.begin():
            await _set_tenant_context(session2, tenant_schema)
            repo = ImageryRepository(session2)
            due = await repo.list_active_subscriptions_due(
                default_cadence_hours=24,  # fallback; per-row cadence applies first
                now=datetime.now(UTC),
            )
        for row in due:
            discover_scenes.delay(str(row["id"]), tenant_schema)
            enqueued += 1
    return {"tenants_scanned": len(tenant_schemas), "enqueued": enqueued}


# --- helpers ---------------------------------------------------------------


async def _fail_job(
    *,
    tenant_schema: str,
    job_id: UUID,
    farm_id: UUID,
    error: str,
) -> None:
    bus = get_default_bus()
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        await repo.mark_failed(
            job_id=job_id,
            completed_at=datetime.now(UTC),
            error_message=error,
        )
    bus.publish(IngestionFailedV1(job_id=job_id, error=error))
    await _record_audit(
        tenant_schema=tenant_schema,
        event_type="imagery.ingestion_failed",
        subject_id=job_id,
        farm_id=farm_id,
        details={"error": error},
    )


def _ninety_days_ago(now: datetime) -> datetime:
    from datetime import timedelta

    return now - timedelta(days=90)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bbox_from_geojson(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    """Compute a 2D bbox from a GeoJSON Polygon/MultiPolygon.

    The block boundary is always a Polygon (data_model § 5.5); guard
    against MultiPolygon for symmetry with farms.
    """
    coords = _flatten_coords(geojson["type"], geojson["coordinates"])
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _flatten_coords(geom_type: str, coords: Any) -> list[tuple[float, float]]:
    if geom_type == "Polygon":
        return [tuple(pt) for ring in coords for pt in ring]
    if geom_type == "MultiPolygon":
        return [tuple(pt) for poly in coords for ring in poly for pt in ring]
    raise ValueError(f"Unsupported geometry type for bbox: {geom_type}")
