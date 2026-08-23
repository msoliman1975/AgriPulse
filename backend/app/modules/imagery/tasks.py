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
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.audit import get_audit_service
from app.modules.imagery.boundary import publish_aoi_boundary
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
from app.modules.imagery.farm_aoi import (
    FarmAoiTooLargeError,
    check_fetchable,
    product_resolution_m,
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
from app.modules.indices.computation import MASK_RULESET, PRODUCT_MASK_RULESETS
from app.modules.indices.tasks import recompute_baselines_for_farm
from app.modules.integrations_health.error_codes import classify_error
from app.modules.weather.service import get_weather_service
from app.shared import backfill_progress
from app.shared.db.ids import uuid7
from app.shared.db.session import AsyncSessionLocal, dispose_engine, sanitize_tenant_schema
from app.shared.eventbus import get_default_bus
from app.shared.storage import StorageClient, get_storage_client

_log = get_logger(__name__)

# Floor for the delay before the first post-backfill baseline recompute. The
# real delay adds two seconds per dispatched scene; this floor covers a run
# that dispatched almost nothing but still needs the queue to turn over.
_BASELINE_RECOMPUTE_MIN_DELAY_S = 120


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Wrap a task body's `asyncio.run` so the global async engine is
    disposed after each task.

    Each Celery task creates a fresh event loop via `asyncio.run`. Our
    async engine is a module-level singleton; without disposal between
    tasks, asyncpg connections retained by the pool reference the
    previous (now-closed) loop, and the next task's pool checkout fails
    with `RuntimeError: Event loop is closed` -> AttributeError on the
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


def _make_provider(provider_code: str) -> ImageryProvider:
    """Construct a provider for the given code.

    The code comes from `public.imagery_providers.code` via
    `_lookup_product`, so adding a provider is one branch here plus a
    catalog row â€” everything downstream (storage keys, pgstac collection
    ids, band order) is already parameterised by product.

    SentinelHubProvider raises SentinelHubNotConfiguredError when the
    creds are empty. Tests inject a fake via `set_provider_factory`.
    """
    if provider_code == "sentinel_hub":
        return SentinelHubProvider()
    if provider_code == "landsat_pc":
        # Imported lazily: the Landsat adapter pulls in rasterio/shapely,
        # and `imagery/service.py` imports this module from an API
        # request path. Same discipline as `_rasterio_io`.
        from app.modules.imagery.providers.landsat_pc import LandsatPlanetaryComputerProvider

        return LandsatPlanetaryComputerProvider()
    raise ValueError(f"Unsupported imagery provider_code: {provider_code!r}")


_provider_factory: Callable[[str], ImageryProvider] = _make_provider


def set_provider_factory(factory: Callable[[str], ImageryProvider]) -> None:
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


async def _air_temp_at_overpass(
    session: AsyncSession,
    *,
    farm_id: UUID,
    scene_time: datetime,
) -> float | None:
    """Air temperature at the satellite overpass minute, or None.

    CWSI is a canopy-to-air temperature difference, and the reading it
    needs almost never lands on one of the hourly samples. The lookup and
    the interpolation both live in the weather module: `imagery` may not
    import `weather.repository` (import contract — module internals are
    private), and it should not have to know the feed is hourly either.

    Never raises: weather is an input to one of three indices, so a
    weather-side failure must not fail an imagery job. Returning None
    costs CWSI alone; LST and SMI still land.
    """
    try:
        return await get_weather_service(tenant_session=session).air_temp_at(
            farm_id=farm_id, at=scene_time
        )
    except Exception as exc:  # weather must not fail an imagery job — see docstring
        _log.warning("imagery_air_temp_lookup_failed", farm_id=str(farm_id), error=str(exc))
        return None


def _assert_farm_aoi_fetchable(farm: dict[str, Any], product: dict[str, Any]) -> None:
    """Raise `_FarmJobFailed` if the farm AOI is too large for the product.

    A whole-farm AOI at 10 m can exceed the provider's per-request pixel
    cap where a single block never would, so this is checked before the
    fetch rather than discovered as an opaque provider error.
    """
    resolution_m = product_resolution_m(product)
    if resolution_m is None:
        return
    try:
        check_fetchable(farm["boundary_utm_geojson"], resolution_m=resolution_m)
    except FarmAoiTooLargeError as exc:
        raise _FarmJobFailed(str(exc), "aoi_too_large") from exc


async def _lookup_product(session: AsyncSession, product_id: UUID) -> dict[str, Any]:
    """Read product code + bands from public.imagery_products."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, code, bands, resolution_m, "
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

    Celery tasks are `system` actors â€” there's no `actor_user_id` on a
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


def _resolve_discovery_window(
    *,
    subscription: dict[str, Any],
    settings: Any,
    now: datetime,
    window_start_override: datetime | None,
    window_end_override: datetime | None,
) -> tuple[datetime, datetime]:
    """Compute the [start, end] catalogue-search window for one discovery.

    A one-shot backfill passes an explicit ``window_start_override`` and the
    watermark/floor is ignored. Otherwise the window runs from the
    subscription's watermark (or the cold-start floor when it has none),
    pulled back by the publication-lag lookback buffer, up to ``now``.
    """
    if window_start_override is not None:
        return window_start_override, (window_end_override or now)
    start = (
        subscription["last_successful_ingest_at"]
        or (now - timedelta(days=settings.imagery_backfill_floor_days))
    ) - timedelta(hours=settings.imagery_discovery_lookback_hours)
    return start, now


async def _touch_if_live(
    repo: ImageryRepository,
    *,
    subscription_id: UUID,
    now: datetime,
    ingested: bool,
    bump_watermark: bool,
) -> None:
    """Record the subscription attempt for a live poll only.

    A backfill (``bump_watermark=False``) must never move the live
    watermark — it ingests old scenes and would otherwise bury recent
    publication-lagged ones.
    """
    if bump_watermark:
        await repo.touch_subscription_attempt(
            subscription_id=subscription_id, attempted_at=now, ingested=ingested
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


async def _discover_scenes_async(
    subscription_id: UUID,
    tenant_schema: str,
    *,
    window_start_override: datetime | None = None,
    window_end_override: datetime | None = None,
    run_compute_indices: bool = True,
    bump_watermark: bool = True,
) -> dict[str, int]:
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
        # retention floor per ARCH Â§9) up to now, pulled back by a lookback
        # buffer. The watermark is wall-clock but the catalogue `from` filter
        # is scene *sensing* time; without the buffer a scene sensed before a
        # poll but published after it falls behind the watermark and is
        # skipped forever. Re-scanning the buffer each poll is safe because
        # `upsert_pending_ingestion_job` is idempotent (already-seen scenes
        # return created=False and are skipped without re-acquisition).
        now = datetime.now(UTC)
        window_start, window_end = _resolve_discovery_window(
            subscription=subscription,
            settings=settings,
            now=now,
            window_start_override=window_start_override,
            window_end_override=window_end_override,
        )

        cloud_cap = _effective_cloud_cap(subscription, settings)

        # SentinelHubProvider raises SentinelHubNotConfiguredError from
        # its constructor when credentials are empty, so the factory
        # call must live inside the try/except â€” otherwise the task
        # dies before the synthetic failed-job marker is written and the
        # UI shows nothing.
        provider: ImageryProvider | None = None
        try:
            try:
                provider = _provider_factory(product["provider_code"])
                scenes = await provider.discover(
                    aoi_geojson=block["boundary_geojson"],
                    product_code=product["code"],
                    from_datetime=window_start,
                    to_datetime=window_end,
                    # No cloud filter here on purpose — see
                    # `_effective_cloud_cap`. Every pass is discovered so
                    # every pass can be shown; the cap decides what is
                    # FETCHED, a few lines below.
                )
            except SentinelHubNotConfiguredError:
                # Configuration failure â€” record one synthetic failed
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
                await _touch_if_live(
                    repo,
                    subscription_id=subscription_id,
                    now=now,
                    ingested=False,
                    bump_watermark=bump_watermark,
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

            if scene.cloud_cover_pct is not None and scene.cloud_cover_pct > cloud_cap:
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

        # `ingested=bool(queued)`: advance the ingest watermark only when this
        # poll actually queued usable imagery. An empty or all-cloud poll still
        # records the attempt (heartbeat) but must NOT bump the watermark —
        # otherwise it would lie about staleness and bury publication-lagged
        # scenes (the original bug). Already-ingested scenes re-seen via the
        # lookback are created=False and don't count toward `queued`.
        #
        # A one-shot backfill (`bump_watermark=False`) is ingesting *old*
        # scenes, so it must not touch the live watermark at all — otherwise it
        # would fast-forward `last_successful_ingest_at` to `now` and make the
        # daily poll skip recent publication-lagged scenes.
        await _touch_if_live(
            repo,
            subscription_id=subscription_id,
            now=now,
            ingested=bool(queued),
            bump_watermark=bump_watermark,
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
            acquire_scene.delay(str(job_id), tenant_schema, run_compute_indices)

    return {
        "discovered": len(scenes),
        "queued": queued,
        "skipped_cloud": skipped_cloud,
    }


# --- backfill (one-shot historical) -----------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.backfill_farm_scenes",
    bind=False,
    ignore_result=True,
)
def backfill_farm_scenes(
    farm_id: str,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
    run_compute_indices: bool = False,
    run_id: str | None = None,
    product_codes: list[str] | None = None,
    progress_source: str = "imagery",
) -> dict[str, int]:
    """Fan out a historical fetch over one farm's active imagery subscriptions.

    One-shot historical backfill entry point. ``from_iso``/``to_iso`` are
    ISO-8601 datetimes (naive is treated as UTC). ``run_compute_indices``
    defaults to False so the block path lands raw bands + STAC only — indices
    can be computed later. (It has no farm-path equivalent: a whole-farm
    acquisition computes its indices inline, as the live path does.)

    Which shape the fan-out takes is decided per subscription, exactly as the
    live sweep decides it — see `_backfill_farm_scenes_async`.

    ``product_codes`` narrows the fan-out; None means every product the farm
    subscribes to. ``progress_source`` names the console counter this run
    reports under. The two travel together: the console offers optical and
    thermal as separate sources, so a thermal run must fetch only thermal
    AND report only under `thermal`. Filtering without renaming the counter
    would show a thermal run's scenes as imagery progress.
    """
    # Same guard as backfill_farm_indices: an unreported crash leaves the
    # run waiting on this source forever.
    backfill_progress.mark_running(run_id)
    try:
        return _run_task(
            _backfill_farm_scenes_async(
                UUID(farm_id),
                tenant_schema,
                from_iso,
                to_iso,
                run_compute_indices,
                run_id,
                product_codes=product_codes,
                progress_source=progress_source,
            )
        )
    except Exception as exc:
        backfill_progress.finish(run_id, progress_source, failed=True, error=str(exc)[:500])
        raise


async def _backfill_farm_scenes_async(
    farm_id: UUID,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
    run_compute_indices: bool,
    run_id: str | None = None,
    *,
    product_codes: list[str] | None = None,
    progress_source: str = "imagery",
) -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        # A cut-over farm is backfilled the way it is fetched live: one
        # whole-farm surface per pass, with the per-block numbers measured off
        # it. The two lists are disjoint by product — a farm can be cut over
        # for Sentinel-2 and still fetch another product per block — so both
        # are dispatched rather than one branch winning outright.
        farm_sub_ids = await repo.list_farm_subscriptions_fetching_aoi(
            farm_id, product_codes=product_codes
        )
        block_sub_ids = await repo.list_block_subscriptions_for_backfill(
            farm_id, product_codes=product_codes
        )

    # This task only fans out — the per-subscription children do the real
    # work and finish long after it returns. So it reports the shape of the
    # job rather than a completion, and settles the source immediately;
    # the console shows scenes landing through the subscription counters.
    # (mark_running already fired in the task wrapper, before this ran.)
    for fsid in farm_sub_ids:
        backfill_farm_aoi_scenes.delay(str(fsid), tenant_schema, from_iso, to_iso)
    for sid in block_sub_ids:
        backfill_scenes.delay(str(sid), tenant_schema, from_iso, to_iso, run_compute_indices)
    _log.info(
        "imagery_backfill_farm_enqueued",
        farm_id=str(farm_id),
        subscriptions=len(block_sub_ids),
        farm_subscriptions=len(farm_sub_ids),
        run_id=run_id,
    )
    backfill_progress.finish(
        run_id,
        progress_source,
        counters={
            "subscriptions": len(block_sub_ids),
            "farm_subscriptions": len(farm_sub_ids),
            "dispatched": True,
        },
        failed=False,
    )
    return {
        "subscriptions_enqueued": len(block_sub_ids),
        "farm_subscriptions_enqueued": len(farm_sub_ids),
    }


# --- farm-wide index recomputation (console "Compute indices") ---------------


def _as_date(value: str) -> date:
    """Parse a window bound that arrives over Celery as a string.

    The console sends ISO dates, but `scripts.backfill_history` and older
    callers can send a full ISO datetime, so accept both rather than
    assuming the shorter form.
    """
    return datetime.fromisoformat(value).date() if "T" in value else date.fromisoformat(value)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.backfill_farm_indices",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def backfill_farm_indices(
    farm_id: str,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
    run_id: str | None = None,
    product_codes: list[str] | None = None,
    progress_source: str = "imagery",
) -> dict[str, int]:
    """Recompute indices for every stored scene of a farm in a window.

    `compute_indices` works per ingestion job, so the console needs this
    farm-level fan-out over scenes that are *already* stored. No provider
    calls and no processing units — it re-reads the raw-bands COG that the
    original ingest wrote.
    """
    # Report a crash against the run, then re-raise. Without this the run's
    # imagery source never reports terminal, `_settle` waits on it forever
    # and the console shows "Queued" for a task that died minutes ago.
    backfill_progress.mark_running(run_id)
    try:
        return _run_task(
            _backfill_farm_indices_async(
                UUID(farm_id),
                tenant_schema,
                from_iso,
                to_iso,
                run_id,
                product_codes=product_codes,
                progress_source=progress_source,
            )
        )
    except Exception as exc:
        backfill_progress.finish(run_id, progress_source, failed=True, error=str(exc)[:500])
        raise


async def _backfill_farm_indices_async(
    farm_id: UUID,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
    run_id: str | None = None,
    *,
    product_codes: list[str] | None = None,
    progress_source: str = "imagery",
) -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        # There is no stored raw-bands key — the ingest derives it from
        # (provider, product, scene, aoi_hash) and writes to that
        # deterministic path. Reconstruct the same inputs here rather than
        # guessing at a column that does not exist.
        # Built in Python rather than bound as a nullable array: passing NULL
        # for a text[] leaves asyncpg with nothing to infer the type from,
        # which is the CAST-plus-bind family of failure this codebase has hit
        # repeatedly. No codes means no clause at all.
        product_clause = "                       AND p.code = ANY(:codes)" if product_codes else ""
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT j.id, j.scene_id, b.aoi_hash,
                           p.code AS product_code, pr.code AS provider_code
                      FROM imagery_ingestion_jobs j
                      JOIN blocks b ON b.id = j.block_id
                      JOIN public.imagery_products p ON p.id = j.product_id
                      JOIN public.imagery_providers pr ON pr.id = p.provider_id
                     WHERE b.farm_id = :farm
                       AND j.status = 'succeeded'
                       AND b.aoi_hash IS NOT NULL
{product_clause}
                       AND j.scene_datetime >= CAST(:window_from AS date)
                       AND j.scene_datetime <  CAST(:window_to AS date) + INTERVAL '1 day'
                     ORDER BY j.scene_datetime ASC
                    """
                ),
                # Real `date` objects, NOT the raw ISO strings. The CAST makes
                # asyncpg type these parameters, so a str raised DataError and
                # killed the task on every run.
                {
                    "farm": farm_id,
                    **({"codes": list(product_codes)} if product_codes else {}),
                    "window_from": _as_date(from_iso),
                    "window_to": _as_date(to_iso),
                },
            )
        ).all()

        # The farm-AOI half. `imagery_ingestion_jobs` above is keyed per
        # BLOCK, so it cannot see a scene fetched for the whole farm — and
        # a cut-over farm has nothing else. Querying only that table made
        # this task report success having recomputed none of the farm's
        # actual scenes: on the reference farm it found 1038 pre-cutover
        # block jobs and zero of the 21 thermal ones. Silent, and worse
        # than an error because it looks like work.
        farm_rows = (
            await session.execute(
                text(
                    f"""
                    SELECT j.id
                      FROM imagery_farm_ingestion_jobs j
                      JOIN public.imagery_products p ON p.id = j.product_id
                     WHERE j.farm_id = :farm
                       AND j.status = 'succeeded'
{product_clause}
                       AND j.scene_datetime >= CAST(:window_from AS date)
                       AND j.scene_datetime <  CAST(:window_to AS date) + INTERVAL '1 day'
                     ORDER BY j.scene_datetime ASC
                    """  # noqa: S608 - product_clause is a literal; codes are bound
                ),
                {
                    "farm": farm_id,
                    **({"codes": list(product_codes)} if product_codes else {}),
                    "window_from": _as_date(from_iso),
                    "window_to": _as_date(to_iso),
                },
            )
        ).all()

    # (mark_running already fired in the task wrapper, before the query.)
    for job_id, scene_id, aoi_hash, product_code, provider_code in rows:
        compute_indices.delay(
            str(job_id),
            tenant_schema,
            raw_bands_key(
                provider_code=provider_code,
                product_code=product_code,
                scene_id=scene_id,
                aoi_hash=aoi_hash,
            ),
        )
    for (farm_job_id,) in farm_rows:
        recompute_farm_scene_indices.delay(str(farm_job_id), tenant_schema)

    # Refresh this farm's index baselines and z-scores once the compute
    # tasks above have had time to land.
    #
    # `block_index_aggregates.baseline_deviation` is derived by
    # `record_aggregate_row` at write time, against whatever baselines exist
    # at that moment. A backfill writes history that has no baseline yet, so
    # those rows land NULL and every decision tree reading
    # `indices.<code>.baseline_deviation` gets nothing.
    #
    # THIS TASK ONLY DISPATCHES. It returns as soon as the `.delay()` calls
    # above are queued, so there is no point recomputing here — the
    # aggregates do not exist yet. There is also no completion signal to
    # wait on: `compute_indices` is `ignore_result=True` (so no chord), and
    # `indices_calc_runs` is empty in every tenant, so it cannot be counted
    # either.
    #
    # So: two delayed shots, sized off the work dispatched. The first covers
    # the normal case, the second covers a slow or contended heavy queue.
    # Both are cheap when nothing changed — the UPDATE carries an
    # `IS DISTINCT FROM` guard, so a run with nothing to fix touches no rows.
    # The hourly `indices.recompute_baselines_sweep` remains the guarantee;
    # these two only make the numbers appear sooner.
    #
    # Nothing dispatched means nothing will be written, so there is nothing to
    # recompute — skip rather than put two pointless jobs on the queue.
    dispatched = len(rows) + len(farm_rows)
    countdowns: list[int] = []
    if dispatched:
        first_delay = min(_BASELINE_RECOMPUTE_MIN_DELAY_S + dispatched * 2, 1800)
        countdowns = [first_delay, first_delay + 1800]
        for countdown in countdowns:
            recompute_baselines_for_farm.apply_async(
                args=[str(farm_id), tenant_schema],
                queue="light",
                countdown=countdown,
            )

    _log.info(
        "imagery_farm_indices_enqueued",
        farm_id=str(farm_id),
        scenes=len(rows),
        farm_scenes=len(farm_rows),
        run_id=run_id,
        baseline_recompute_countdowns=countdowns,
    )
    backfill_progress.finish(
        run_id,
        progress_source,
        counters={
            "scenes": len(rows),
            # Reported separately, not folded into `scenes`. A cut-over farm
            # has both shapes in its history, and one number could not say
            # which half a run actually touched.
            "farm_scenes": len(farm_rows),
            "dispatched": True,
        },
        failed=False,
    )
    return {"scenes_enqueued": len(rows), "farm_scenes_enqueued": len(farm_rows)}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.recompute_farm_scene_indices",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def recompute_farm_scene_indices(job_id: str, tenant_schema: str) -> dict[str, Any]:
    """Recompute indices for one already-fetched farm-AOI scene.

    The farm-path counterpart to `compute_indices`. That task keys on
    `imagery_ingestion_jobs` (per block); this one keys on
    `imagery_farm_ingestion_jobs`, whose scenes it could never see.

    Re-reads the raw COG already in object storage — no provider call, no
    quota, nothing refetched.
    """
    return _run_task(_recompute_farm_scene_indices_async(UUID(job_id), tenant_schema))


async def _recompute_farm_scene_indices_async(job_id: UUID, tenant_schema: str) -> dict[str, Any]:
    storage = _get_storage()
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        job = await repo.get_farm_job(job_id)
        if job is None:
            return {"job_id": str(job_id), "status": "missing"}
        # Only a scene that actually landed has a raster to read back.
        if job["status"] != "succeeded":
            return {"job_id": str(job_id), "status": job["status"], "noop": True}
        farm = await repo.get_farm_boundary(job["farm_id"])
        if farm is None:
            return {"job_id": str(job_id), "status": "farm_missing"}
        product = await _lookup_product(session, job["product_id"])
        air_temp_c = (
            await _air_temp_at_overpass(
                session, farm_id=job["farm_id"], scene_time=job["scene_datetime"]
            )
            if product["code"] == "landsat_c2_l2_st"
            else None
        )

    s3_key = raw_bands_key(
        provider_code=product["provider_code"],
        product_code=product["code"],
        scene_id=job["scene_id"],
        aoi_hash=farm["aoi_hash"],
    )
    try:
        index_keys, _stac_item_id, aggregates_written = await _compute_farm_scene_indices(
            tenant_schema=tenant_schema,
            job=job,
            farm=farm,
            product=product,
            storage=storage,
            s3_key=s3_key,
            air_temp_c=air_temp_c,
        )
    except _FarmJobFailed as failure:
        # Deliberately does NOT flip the job to failed. The scene was
        # fetched and stored successfully; only this recompute failed, and
        # rewriting history to say the acquisition failed would lose that.
        _log.warning(
            "farm_scene_indices_recompute_failed",
            tenant_schema=tenant_schema,
            job_id=str(job_id),
            scene_id=job["scene_id"],
            error=failure.message,
            error_code=failure.code,
        )
        return {"job_id": str(job_id), "status": "failed", "error": failure.message}

    _log.info(
        "farm_scene_indices_recomputed",
        tenant_schema=tenant_schema,
        farm_id=str(job["farm_id"]),
        scene_id=job["scene_id"],
        product=product["code"],
        indices=len(index_keys),
        block_aggregates=aggregates_written,
    )
    return {
        "job_id": str(job_id),
        "status": "succeeded",
        "indices": sorted(index_keys),
        "block_aggregates": aggregates_written,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.backfill_scenes",
    bind=False,
    ignore_result=True,
)
def backfill_scenes(
    subscription_id: str,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
    run_compute_indices: bool = False,
) -> dict[str, int]:
    """Discover + acquire scenes for one subscription over an explicit window.

    Bypasses the cold-start floor and the live watermark, and does NOT
    advance the watermark (so the daily poll's publication-lag safety is
    preserved). Cloud-over-cap scenes are still skipped. Idempotent via the
    (subscription_id, scene_id) UNIQUE — re-running is safe.
    """
    start = datetime.fromisoformat(from_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    end = datetime.fromisoformat(to_iso)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return _run_task(
        _discover_scenes_async(
            UUID(subscription_id),
            tenant_schema,
            window_start_override=start,
            window_end_override=end,
            run_compute_indices=run_compute_indices,
            bump_watermark=False,
        )
    )


# --- acquire_scene ----------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.acquire_scene",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def acquire_scene(
    job_id: str, tenant_schema: str, run_compute_indices: bool = True
) -> dict[str, Any]:
    return _run_task(_acquire_scene_async(UUID(job_id), tenant_schema, run_compute_indices))


async def _acquire_scene_async(
    job_id: UUID, tenant_schema: str, run_compute_indices: bool = True
) -> dict[str, Any]:
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
                error_code="config_error",
            )
            bus.publish(IngestionFailedV1(job_id=job_id, error="block_missing"))
            return {"job_id": str(job_id), "status": "failed"}
        product = await _lookup_product(session, job["product_id"])
        await repo.mark_running(job_id=job_id, started_at=datetime.now(UTC))

    # Step 2: fetch from the provider.
    provider = _provider_factory(product["provider_code"])
    try:
        try:
            result = await provider.fetch(
                scene_id=job["scene_id"],
                scene_datetime=job["scene_datetime"],
                product_code=product["code"],
                aoi_geojson_utm=block["boundary_utm_geojson"],
                aoi_srid=block["utm_srid"],
                bands=tuple(product["bands"]),
            )
        except Exception as exc:
            await _fail_job(
                tenant_schema=tenant_schema,
                job_id=job_id,
                farm_id=block["farm_id"],
                error=str(exc) or exc.__class__.__name__,
                error_code=classify_error(exc),
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
            error_code="storage_error",
        )
        return {"job_id": str(job_id), "status": "failed"}

    # Step 4: chain register_stac_item with the assets we just wrote.
    register_stac_item.delay(str(job_id), tenant_schema, [s3_key], run_compute_indices)
    return {"job_id": str(job_id), "status": "running", "asset_key": s3_key}


# --- register_stac_item -----------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.register_stac_item",
    bind=False,
    ignore_result=True,
)
def register_stac_item(
    job_id: str,
    tenant_schema: str,
    assets_written: list[str],
    run_compute_indices: bool = True,
) -> dict[str, Any]:
    return _run_task(
        _register_stac_item_async(UUID(job_id), tenant_schema, assets_written, run_compute_indices)
    )


async def _register_stac_item_async(
    job_id: UUID,
    tenant_schema: str,
    assets_written: list[str],
    run_compute_indices: bool = True,
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
                error_code="config_error",
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
                    "agripulse:scene_id": job["scene_id"],
                    "agripulse:aoi_hash": block["aoi_hash"],
                },
            )
            await upsert_item(session, item_doc=item_doc)
        except Exception as exc:
            await repo.mark_failed(
                job_id=job_id,
                completed_at=datetime.now(UTC),
                error_message=f"stac_register_failed: {exc}",
                error_code="stac_register_failed",
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

    # Chain compute_indices â€” runs on the heavy queue (rasterio reads
    # are CPU + IO heavy). Failure here doesn't roll back the
    # registration; the job stays `succeeded` and a separate retry
    # tool can re-trigger compute on demand (P2). A raw-only backfill
    # passes run_compute_indices=False to land bands + STAC only.
    if run_compute_indices:
        compute_indices.delay(str(job_id), tenant_schema, assets_written[0])

    return {"job_id": str(job_id), "status": "succeeded", "stac_item_id": item_id}


# --- compute_indices --------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.build_farm_scene_raster",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def build_farm_scene_raster(farm_id: str, tenant_schema: str, at_iso: str) -> dict[str, Any]:
    """Stitch one farm-wide raster for one pass, from bands already stored.

    Imagery is fetched per BLOCK, so a 36-block farm holds 36 rasters per pass
    and no pixels at all between the blocks. This merges those rasters into one
    surface and writes the per-index COGs against the FARM's aoi hash, which is
    what lets the console draw a farm from a single tile source with no seams
    where blocks meet.

    Reads only what is already in the bucket: no provider call, no quota.
    """
    return _run_task(
        _build_farm_scene_raster_async(UUID(farm_id), tenant_schema, datetime.fromisoformat(at_iso))
    )


async def _build_farm_scene_raster_async(
    farm_id: UUID,
    tenant_schema: str,
    at: datetime,
) -> dict[str, Any]:
    storage = _get_storage()

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        sources = await repo.list_farm_scene_sources(farm_id=farm_id, scene_datetime=at)
        if sources is None:
            return {"farm_id": str(farm_id), "at": at.isoformat(), "status": "no_sources"}
        product = await _lookup_product(session, sources["product_id"])

    # Local import: rasterio and numpy belong to the heavy worker only.
    from app.modules.imagery._rasterio_io import compute_and_write_indices
    from app.modules.imagery.farm_raster import (
        NoBlockRastersError,
        covered_mask,
        merge_block_rasters,
    )

    bucket = storage.bucket
    raw_uris = [f"s3://{bucket}/{stac}/raw_bands.tif" for stac in sources["stac_item_ids"]]
    try:
        bands_arrays, cloud_mask, profile = merge_block_rasters(
            raw_uris,
            band_names=tuple(product["bands"]),
            resolution_m=product_resolution_m(product),
        )
    except NoBlockRastersError:
        # Every block of this pass claims success with no object behind it —
        # the shape of the 3,787 orphans on prod. Nothing to build, and saying
        # so is more useful than a raster of pure nodata.
        return {"farm_id": str(farm_id), "at": at.isoformat(), "status": "no_readable_rasters"}

    _aggregates, index_keys, _rasters = compute_and_write_indices(
        bands_arrays=bands_arrays,
        # The farm surface IS the union of what was fetched; anything else is
        # nodata and must stay out of every statistic.
        aoi_mask=covered_mask(bands_arrays),
        profile=profile,
        storage=storage,
        provider_code=product["provider_code"],
        product_code=product["code"],
        scene_id=sources["scene_id"],
        aoi_hash=sources["farm_aoi_hash"],
        cloud_mask=cloud_mask,
    )
    stac_item_id = (
        f"{product['provider_code']}/{product['code']}/"
        f"{sources['scene_id']}/{sources['farm_aoi_hash']}"
    )
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        await ImageryRepository(session).record_farm_scene_raster(
            farm_id=farm_id,
            product_id=sources["product_id"],
            scene_datetime=sources["scene_datetime"],
            scene_id=sources["scene_id"],
            stac_item_id=stac_item_id,
            aoi_hash=sources["farm_aoi_hash"],
            blocks_merged=len(sources["stac_item_ids"]),
            indices=sorted(index_keys),
        )

    _log.info(
        "farm_raster_built",
        tenant_schema=tenant_schema,
        farm_id=str(farm_id),
        at=at.isoformat(),
        blocks_merged=len(sources["stac_item_ids"]),
        indices=len(index_keys),
    )
    return {
        "farm_id": str(farm_id),
        "at": at.isoformat(),
        "status": "built",
        "blocks_merged": len(sources["stac_item_ids"]),
        "indices": sorted(index_keys),
        "aoi_hash": sources["farm_aoi_hash"],
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.verify_farm_raster_aggregates",
    bind=False,
    ignore_result=False,
    queue="heavy",
)
def verify_farm_raster_aggregates(farm_id: str, tenant_schema: str, at_iso: str) -> dict[str, Any]:
    """Do block means computed from the FARM surface match the stored ones?

    The whole cutover rests on one claim: measuring a block from a farm-wide
    raster gives the same number as measuring it from its own. This checks that
    claim against rows the per-block pipeline already wrote, and WRITES
    NOTHING — it is evidence, not a migration.

    A non-trivial difference means the two paths are not looking at the same
    pixels, and the cutover should stop until it is understood.
    """
    return _run_task(
        _verify_farm_raster_aggregates_async(
            UUID(farm_id), tenant_schema, datetime.fromisoformat(at_iso)
        )
    )


async def _verify_farm_raster_aggregates_async(
    farm_id: UUID,
    tenant_schema: str,
    at: datetime,
) -> dict[str, Any]:
    storage = _get_storage()

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        sources = await repo.list_farm_scene_sources(farm_id=farm_id, scene_datetime=at)
        if sources is None:
            return {"farm_id": str(farm_id), "at": at.isoformat(), "status": "no_sources"}
        product = await _lookup_product(session, sources["product_id"])
        boundaries = await repo.list_farm_block_boundaries(farm_id)
        stored = await repo.list_block_index_means(farm_id=farm_id, scene_datetime=at)

    if not stored:
        return {"farm_id": str(farm_id), "at": at.isoformat(), "status": "no_stored_aggregates"}

    import json as _json

    import numpy as np

    from app.modules.imagery.farm_raster import (
        NoBlockRastersError,
        block_masks_on_grid,
        covered_mask,
        merge_block_rasters,
    )
    from app.modules.indices.computation import compute_aggregates, compute_all_indices

    bucket = storage.bucket
    raw_uris = [f"s3://{bucket}/{stac}/raw_bands.tif" for stac in sources["stac_item_ids"]]
    try:
        bands_arrays, cloud_mask, profile = merge_block_rasters(
            raw_uris, band_names=tuple(product["bands"])
        )
    except NoBlockRastersError:
        return {"farm_id": str(farm_id), "at": at.isoformat(), "status": "no_readable_rasters"}

    masks = block_masks_on_grid(
        profile,
        {str(b["block_id"]): _json.loads(b["boundary_utm_geojson"]) for b in boundaries},
    )
    surface = covered_mask(bands_arrays)
    has_cloud = bool(cloud_mask.any())

    deltas: list[float] = []
    compared = 0
    missing = 0
    worst: dict[str, Any] | None = None
    for index_code, raster in compute_all_indices(bands_arrays).items():
        clouded = np.where(cloud_mask, np.float32("nan"), raster) if has_cloud else raster
        for block_id, mask in masks.items():
            was = stored.get((block_id, index_code))
            if was is None:
                missing += 1
                continue
            agg = compute_aggregates(clouded, mask & surface)
            if agg.mean is None:
                missing += 1
                continue
            delta = abs(float(agg.mean) - was)
            deltas.append(delta)
            compared += 1
            if worst is None or delta > worst["delta"]:
                worst = {
                    "delta": delta,
                    "block_id": block_id,
                    "index": index_code,
                    "stored": was,
                    "from_farm": float(agg.mean),
                }

    result = {
        "farm_id": str(farm_id),
        "at": at.isoformat(),
        "status": "compared",
        "compared": compared,
        "no_baseline": missing,
        "max_abs_delta": max(deltas) if deltas else None,
        "mean_abs_delta": (sum(deltas) / len(deltas)) if deltas else None,
        "worst": worst,
    }
    _log.info("farm_raster_aggregate_diff", tenant_schema=tenant_schema, **result)
    return result


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.rebuild_farm_rasters",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def rebuild_farm_rasters(farm_id: str, tenant_schema: str, limit: int = 250) -> dict[str, Any]:
    """Fan out `build_farm_scene_raster` across a farm's history.

    One task per pass rather than one long task: a farm has hundreds of them,
    and a single failure should cost one scene rather than the whole rebuild.
    """
    return _run_task(_rebuild_farm_rasters_async(UUID(farm_id), tenant_schema, limit))


async def _rebuild_farm_rasters_async(
    farm_id: UUID,
    tenant_schema: str,
    limit: int,
) -> dict[str, Any]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        instants = await ImageryRepository(session).list_farm_scene_instants(
            farm_id=farm_id, limit=limit
        )
    for at in instants:
        build_farm_scene_raster.delay(str(farm_id), tenant_schema, at.isoformat())
    _log.info(
        "farm_raster_rebuild_queued",
        tenant_schema=tenant_schema,
        farm_id=str(farm_id),
        scenes=len(instants),
    )
    return {"farm_id": str(farm_id), "queued": len(instants)}


# --- farm-AOI ingestion -----------------------------------------------------
#
# The block path fetches one AOI per block, so ground no block was drawn around
# is not merely uncoloured but unmeasured — 50.3 of 203.4 feddan on the
# reference farm. Stitching those blocks inherits the hole; only fetching the
# farm boundary fills it.
#
# This runs ALONGSIDE the block path rather than replacing it: block rasters
# still produce block_index_aggregates, which is where every number in the
# product comes from. The farm fetch produces the surface the console draws.
# Two fetches for an opted-in farm is the cost of that decision, and it is why
# `fetch_farm_aoi` defaults to FALSE.


async def _compute_farm_scene_indices(
    *,
    tenant_schema: str,
    job: dict[str, Any],
    farm: dict[str, Any],
    product: dict[str, Any],
    storage: StorageClient,
    s3_key: str,
    air_temp_c: float | None,
) -> tuple[dict[str, str], str, int]:
    """Compute one farm scene's indices from its stored raw COG.

    Everything after the fetch: read the raster back, compute the
    product's index set, write each index COG, and measure every block
    off that surface.

    Shared by the two callers deliberately. `_acquire_farm_scene_async`
    runs it right after storing the bytes; `_recompute_farm_scene_indices
    _async` runs it against a scene fetched days ago. They had every
    reason to drift apart — one has a provider in hand and the other does
    not — and a farm-path recompute that computed indices slightly
    differently from the live path would be nearly impossible to spot,
    because both produce plausible numbers.

    Returns ``(index_keys, stac_item_id, block_aggregates_written)``.
    Raises `_FarmJobFailed` with the same error codes the live path used.
    """
    # Local import: rasterio and numpy belong to the heavy worker only.
    from app.modules.imagery._rasterio_io import (
        compute_and_write_indices,
        load_raw_bands_and_aggregate,
    )

    # The outline the tile server cuts this scene's tiles with. Written on
    # every compute rather than once: it is content-addressed, so a repeat
    # is the same bytes, and a farm redrawn gets its new outline with its
    # first new scene. Never fatal - see boundary.py.
    publish_aoi_boundary(
        storage,
        aoi_hash=farm.get("aoi_hash"),
        boundary_geojson=farm.get("boundary_geojson"),
    )

    try:
        bands_arrays, aoi_mask, cloud_mask, profile = load_raw_bands_and_aggregate(
            f"s3://{storage.bucket}/{s3_key}",
            band_names=tuple(product["bands"]),
            aoi_geojson_utm=farm["boundary_utm_geojson"],
            product_code=product["code"],
            # Cut at the boundary, not one pixel past it. This surface is
            # DRAWN, over the farm's own outline, and the touched rule paints
            # every pixel the border clips through — a staircase of colour
            # outside the farm, 10 m wide on Sentinel-2 and 30 m on Landsat.
            # The block path keeps the touched rule; see the parameter's note.
            all_touched=False,
        )
        _aggregates, index_keys, index_rasters = compute_and_write_indices(
            bands_arrays=bands_arrays,
            aoi_mask=aoi_mask,
            cloud_mask=cloud_mask,
            profile=profile,
            storage=storage,
            provider_code=product["provider_code"],
            product_code=product["code"],
            scene_id=job["scene_id"],
            aoi_hash=farm["aoi_hash"],
            air_temp_c=air_temp_c,
        )
    except Exception as exc:
        raise _FarmJobFailed(f"compute_indices_failed: {exc}", "compute_error") from exc

    stac_item_id = (
        f"{product['provider_code']}/{product['code']}/{job['scene_id']}/{farm['aoi_hash']}"
    )

    # Measure every block off this surface. Without it, switching a farm to
    # farm-AOI fetching would leave Insights, alerts, recommendations and
    # baselines with no new numbers at all — the surface would look right and
    # every figure beside it would quietly stop moving.
    try:
        aggregates_written = await _write_block_aggregates_from_farm(
            tenant_schema=tenant_schema,
            farm_id=job["farm_id"],
            product_id=job["product_id"],
            scene_datetime=job["scene_datetime"],
            stac_item_id=stac_item_id,
            cloud_cover_pct=job["cloud_cover_pct"],
            index_rasters=index_rasters,
            profile=profile,
        )
    except Exception as exc:
        raise _FarmJobFailed(f"block_aggregates_failed: {exc}", "compute_error") from exc

    return index_keys, stac_item_id, aggregates_written


async def _write_block_aggregates_from_farm(
    *,
    tenant_schema: str,
    farm_id: UUID,
    product_id: UUID,
    scene_datetime: datetime,
    stac_item_id: str,
    cloud_cover_pct: Any,
    index_rasters: dict[str, Any],
    profile: dict[str, Any],
) -> int:
    """Measure every block off the farm surface and store the numbers.

    This is what lets the per-block FETCH stop. Every index number in the
    product — Insights, alerts, recommendations, baselines, grid cells —
    reads `block_index_aggregates`, which until now only the per-block
    pipeline wrote. Measuring the same block from the farm-wide raster gives
    the same answer to about 0.001 NDVI (measured over ~1,500 comparisons
    spanning 2.5 years), so the numbers keep their meaning.

    The rows record the FARM's stac_item_id, because that is the raster the
    numbers were actually taken from. A reader tracing a value back finds the
    surface it came from rather than a per-block object that no longer exists.
    """
    import json as _json

    from app.modules.grid.service import get_grid_service
    from app.modules.grid.zonal import compute_cell_aggregates
    from app.modules.imagery.farm_raster import block_masks_on_grid
    from app.modules.indices.computation import compute_aggregates
    from app.modules.indices.service import get_indices_service

    if not index_rasters:
        # Nothing was computed, so there is nothing to measure. Better than
        # reaching into an empty profile and failing the whole fetch.
        return 0

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        boundaries = await ImageryRepository(session).list_farm_block_boundaries(farm_id)

    if not boundaries:
        return 0

    masks = block_masks_on_grid(
        profile,
        {str(b["block_id"]): _json.loads(b["boundary_utm_geojson"]) for b in boundaries},
    )

    written = 0
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        indices_service = get_indices_service(tenant_session=session)
        grid_service = get_grid_service(tenant_session=session)

        for block_id, mask in masks.items():
            for index_code, raster in index_rasters.items():
                agg = compute_aggregates(raster, mask)
                if agg.mean is None:
                    # The block is entirely cloud or entirely outside what the
                    # pass covered. Writing a row of nulls would look like a
                    # measurement; absence is the honest record.
                    continue
                await indices_service.record_aggregate_row(
                    time=scene_datetime,
                    block_id=UUID(block_id),
                    index_code=index_code,
                    product_id=product_id,
                    stac_item_id=stac_item_id,
                    mean=agg.mean,
                    min_value=agg.min,
                    max_value=agg.max,
                    p10=agg.p10,
                    p50=agg.p50,
                    p90=agg.p90,
                    std_dev=agg.std_dev,
                    valid_pixel_count=agg.valid_pixel_count,
                    total_pixel_count=agg.total_pixel_count,
                    cloud_cover_pct=cloud_cover_pct,
                )
                written += 1

            # Sub-block cells, resolved at the SCENE's time rather than "the
            # current grid" — the per-block path learned that in 0054, and
            # gridding an old scene on a new geometry writes rows no
            # valid-time-aware read can return.
            cells = await grid_service.list_cells_for_scene(
                block_id=UUID(block_id), product_id=product_id, at=scene_datetime
            )
            if cells:
                per_cell_per_index = _zonal_by_cell(
                    cells=cells,
                    index_rasters=index_rasters,
                    raster_transform=profile["transform"],
                    compute_cell_aggregates=compute_cell_aggregates,
                )
                await grid_service.record_grid_aggregates(
                    scene_time=scene_datetime,
                    block_id=UUID(block_id),
                    product_id=product_id,
                    stac_item_id=stac_item_id,
                    cloud_cover_pct=cloud_cover_pct,
                    per_cell_per_index=per_cell_per_index,
                )
    return written


async def _record_farm_scene_success(
    *,
    tenant_schema: str,
    job: dict[str, Any],
    job_id: UUID,
    aoi_hash: str,
    stac_item_id: str,
    raw_bands_s3_key: str,
    index_keys: dict[str, str],
) -> None:
    """Record the surface and close the job, in one transaction."""
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        await repo.record_farm_scene_raster(
            farm_id=job["farm_id"],
            product_id=job["product_id"],
            scene_datetime=job["scene_datetime"],
            scene_id=job["scene_id"],
            stac_item_id=stac_item_id,
            aoi_hash=aoi_hash,
            # Nothing was merged — this surface was photographed as one.
            blocks_merged=None,
            indices=sorted(index_keys),
            source="fetched",
        )
        await repo.set_farm_job_status(
            job_id=job_id,
            status="succeeded",
            completed_at=datetime.now(UTC),
            stac_item_id=stac_item_id,
            # index_keys maps code -> written key; assets_written wants the
            # keys. Iterating the dict gives the codes, which recorded
            # "ndvi" where an object path belonged.
            assets_written=[raw_bands_s3_key, *sorted(index_keys.values())],
        )


class _FarmJobFailed(Exception):
    """Internal: carries the message and code to one shared failure exit."""

    def __init__(self, message: str, code: str | None) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


async def _fail_farm_job(
    *,
    tenant_schema: str,
    job_id: UUID,
    farm_id: UUID,
    error: str,
    error_code: str | None,
) -> None:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        await ImageryRepository(session).set_farm_job_status(
            job_id=job_id,
            status="failed",
            completed_at=datetime.now(UTC),
            error_message=error[:1000],
            error_code=error_code,
        )
    await _record_audit(
        tenant_schema=tenant_schema,
        event_type="imagery.ingestion_failed",
        subject_id=job_id,
        farm_id=farm_id,
        details={"error": error, "scope": "farm"},
    )


def _effective_cloud_cap(subscription: dict[str, Any], settings: Any) -> int:
    """The cloud percentage above which a pass is recorded but not fetched.

    Deliberately NOT handed to the provider's search. A server-side
    ``eo:cloud_cover<=N`` filter does not reject scenes — it makes them
    **never have existed**: no job row, no timeline entry, no reason. The
    scene strip is built to say "cloudy" over a gap precisely so an operator
    can tell weather from a broken pipeline, and it cannot say anything about
    a scene it was never told about.

    Measured on prod: greenFarm_Test's subscriptions carry a cap of **0**, so
    a single cloud anywhere in a 110 km Sentinel-2 tile deleted the whole
    pass. Sixteen scenes survived three months, with unexplained gaps of 12
    and 20 days, on a farm under an almost cloudless sky. Every surviving job
    reads exactly `0.0%` cloud, which is the tell: nothing else could ever
    have been discovered.

    The platform setting stays a CEILING as well as the default. A per-farm
    cap can therefore lower what is pulled but not raise it, so this change
    cannot spend more at the provider than the previous behaviour did —
    raising a farm above the platform ceiling stays a deliberate act.
    """
    ceiling = int(settings.imagery_cloud_cover_visualization_max_pct)
    own = subscription["cloud_cover_max_pct"]
    return ceiling if own is None else min(int(own), ceiling)


async def _queue_farm_jobs(
    repo: ImageryRepository,
    *,
    bus: Any,
    cloud_cap: int,
    scenes: tuple[Any, ...],
    subscription: dict[str, Any],
    farm_id: UUID,
    now: datetime,
) -> tuple[int, int]:
    """Insert one job per newly seen scene; return (queued, skipped_cloud).

    Same shape as the block path: a scene already seen is created=False and
    contributes to neither count, which is what makes re-discovery free.

    Over-cap scenes are RECORDED, then skipped. That is the whole point of
    writing a row for them — see `_effective_cloud_cap`.
    """
    queued = 0
    skipped_cloud = 0
    for scene in scenes:
        new_id, created = await repo.upsert_pending_farm_job(
            job_id=uuid7(),
            subscription_id=subscription["id"],
            farm_id=farm_id,
            product_id=subscription["product_id"],
            scene_id=scene.scene_id,
            scene_datetime=scene.scene_datetime,
            cloud_cover_pct=scene.cloud_cover_pct,
        )
        if not created:
            continue
        too_cloudy = scene.cloud_cover_pct is not None and scene.cloud_cover_pct > cloud_cap
        if too_cloudy:
            await repo.set_farm_job_status(
                job_id=new_id,
                status="skipped",
                completed_at=now,
                error_message="cloud",
            )
            bus.publish(SceneSkippedV1(job_id=new_id, reason="cloud"))
            skipped_cloud += 1
        else:
            queued += 1
    return queued, skipped_cloud


async def _touch_farm_if_live(
    repo: ImageryRepository,
    *,
    subscription_id: UUID,
    now: datetime,
    ingested: bool,
    bump_watermark: bool,
) -> None:
    """Farm-path twin of `_touch_if_live`.

    A backfill (``bump_watermark=False``) reaches back over old passes, so
    letting it move `last_successful_ingest_at` forward would make the next
    live poll start after scenes it has never seen.
    """
    if bump_watermark:
        await repo.touch_farm_subscription_attempt(
            subscription_id=subscription_id, attempted_at=now, ingested=ingested
        )


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.discover_farm_scenes",
    bind=False,
    ignore_result=True,
)
def discover_farm_scenes(subscription_id: str, tenant_schema: str) -> dict[str, int]:
    """Find passes over one farm's own boundary."""
    return _run_task(_discover_farm_scenes_async(UUID(subscription_id), tenant_schema))


async def _discover_farm_scenes_async(
    subscription_id: UUID,
    tenant_schema: str,
    *,
    window_start_override: datetime | None = None,
    window_end_override: datetime | None = None,
    bump_watermark: bool = True,
) -> dict[str, int]:
    settings = get_settings()
    bus = get_default_bus()
    empty = {"discovered": 0, "queued": 0, "skipped_cloud": 0}

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)

        subscription = await repo.get_farm_subscription(subscription_id)
        if subscription is None or not subscription["fetch_farm_aoi"]:
            # The switch can be turned off between the beat sweep and here.
            return empty
        farm_id = subscription["farm_id"]
        farm = await repo.get_farm_boundary(farm_id)
        if farm is None:
            _log.warning(
                "imagery_discover_farm_boundary_missing",
                subscription_id=str(subscription_id),
                farm_id=str(farm_id),
            )
            return empty
        product = await _lookup_product(session, subscription["product_id"])

        # Refuse a farm the provider could not return in one request, before
        # spending the call. Recorded as an attempt so the poll does not spin.
        resolution_m = product_resolution_m(product)
        if resolution_m is not None:
            try:
                check_fetchable(farm["boundary_utm_geojson"], resolution_m=resolution_m)
            except FarmAoiTooLargeError as exc:
                _log.warning(
                    "imagery_farm_aoi_too_large",
                    tenant_schema=tenant_schema,
                    farm_id=str(farm_id),
                    width_px=exc.width_px,
                    height_px=exc.height_px,
                )
                # Fall back to the block path instead of returning empty
                # forever. `fetch_farm_aoi` is what excludes this farm's blocks
                # from the block sweep, so leaving it on while refusing to
                # fetch the farm means the farm gets NO imagery from either
                # path — the flag has to come off for the blocks to resume.
                await repo.disable_farm_aoi_fetch(subscription_id=subscription_id)
                await _touch_farm_if_live(
                    repo,
                    subscription_id=subscription_id,
                    now=datetime.now(UTC),
                    ingested=False,
                    bump_watermark=bump_watermark,
                )
                # Logged, not audited. The audit service opens its own session,
                # and taking a second connection while this transaction is open
                # is the shape that exhausted the pool before — every other
                # audit in this module is written after its transaction closes,
                # and there is no such point on this path.
                return empty

        now = datetime.now(UTC)
        window_start, window_end = _resolve_discovery_window(
            subscription=subscription,
            settings=settings,
            now=now,
            window_start_override=window_start_override,
            window_end_override=window_end_override,
        )
        cloud_cap = _effective_cloud_cap(subscription, settings)

        provider: ImageryProvider | None = None
        try:
            try:
                provider = _provider_factory(product["provider_code"])
                scenes = await provider.discover(
                    aoi_geojson=farm["boundary_geojson"],
                    product_code=product["code"],
                    from_datetime=window_start,
                    to_datetime=window_end,
                    # Unfiltered, as on the block path — see
                    # `_effective_cloud_cap`.
                )
            except SentinelHubNotConfiguredError:
                # No synthetic marker row here: the block path already writes
                # one per subscription and a second copy per farm would double
                # the noise for one misconfiguration.
                await _touch_farm_if_live(
                    repo,
                    subscription_id=subscription_id,
                    now=now,
                    ingested=False,
                    bump_watermark=bump_watermark,
                )
                return empty
        finally:
            if provider is not None and hasattr(provider, "aclose"):
                await provider.aclose()

        queued, skipped_cloud = await _queue_farm_jobs(
            repo,
            bus=bus,
            cloud_cap=cloud_cap,
            scenes=scenes,
            subscription=subscription,
            farm_id=farm_id,
            now=now,
        )

        await _touch_farm_if_live(
            repo,
            subscription_id=subscription_id,
            now=now,
            ingested=bool(queued),
            bump_watermark=bump_watermark,
        )

    # Outside the transaction, so the rows are visible to the worker.
    if queued:
        async with AsyncSessionLocal()() as session2, session2.begin():
            await _set_tenant_context(session2, tenant_schema)
            pending = await ImageryRepository(session2).list_pending_farm_jobs(
                subscription_id=subscription_id
            )
        for job_id in pending:
            acquire_farm_scene.delay(str(job_id), tenant_schema)

    return {"discovered": len(scenes), "queued": queued, "skipped_cloud": skipped_cloud}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.backfill_farm_aoi_scenes",
    bind=False,
    ignore_result=True,
)
def backfill_farm_aoi_scenes(
    subscription_id: str,
    tenant_schema: str,
    from_iso: str,
    to_iso: str,
) -> dict[str, int]:
    """Discover + acquire whole-farm passes over an explicit window.

    The farm-path twin of `backfill_scenes`. Same contract: the cold-start
    floor and the live watermark are bypassed, the watermark is NOT advanced,
    and re-running is free because (subscription_id, scene_id) is UNIQUE.

    Backfilling a cut-over farm this way is what keeps its history the same
    shape as its live data — one farm surface per pass, with block aggregates
    measured off it — instead of a second, block-shaped history sitting
    beside it in different tables.
    """
    start = datetime.fromisoformat(from_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    end = datetime.fromisoformat(to_iso)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return _run_task(
        _discover_farm_scenes_async(
            UUID(subscription_id),
            tenant_schema,
            window_start_override=start,
            window_end_override=end,
            bump_watermark=False,
        )
    )


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.acquire_farm_scene",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def acquire_farm_scene(job_id: str, tenant_schema: str) -> dict[str, Any]:
    """Fetch one pass over the whole farm and write its index rasters.

    The fetched surface replaces a stitched one for the same pass: it covers
    ground no block was drawn around, so it is strictly wider.
    """
    return _run_task(_acquire_farm_scene_async(UUID(job_id), tenant_schema))


async def _acquire_farm_scene_async(job_id: UUID, tenant_schema: str) -> dict[str, Any]:
    storage = _get_storage()
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = ImageryRepository(session)
        job = await repo.get_farm_job(job_id)
        if job is None:
            return {"job_id": str(job_id), "status": "missing"}
        if job["status"] != "pending":
            return {"job_id": str(job_id), "status": job["status"], "noop": True}
        farm = await repo.get_farm_boundary(job["farm_id"])
        if farm is None:
            await repo.set_farm_job_status(
                job_id=job_id,
                status="failed",
                completed_at=datetime.now(UTC),
                error_message="farm_missing",
                error_code="config_error",
            )
            return {"job_id": str(job_id), "status": "failed"}
        product = await _lookup_product(session, job["product_id"])
        # Only the thermal product needs it, and only for CWSI.
        farm_air_temp_c = (
            await _air_temp_at_overpass(
                session, farm_id=job["farm_id"], scene_time=job["scene_datetime"]
            )
            if product["code"] == "landsat_c2_l2_st"
            else None
        )
        await repo.set_farm_job_status(
            job_id=job_id, status="running", started_at=datetime.now(UTC)
        )

    # Every failure below lands in one place: the job is marked failed with a
    # code, once, rather than at eight separate exits.
    try:
        _assert_farm_aoi_fetchable(farm, product)

        provider = _provider_factory(product["provider_code"])
        try:
            try:
                result = await provider.fetch(
                    scene_id=job["scene_id"],
                    scene_datetime=job["scene_datetime"],
                    product_code=product["code"],
                    aoi_geojson_utm=farm["boundary_utm_geojson"],
                    aoi_srid=farm["utm_srid"],
                    bands=tuple(product["bands"]),
                )
            except Exception as exc:
                raise _FarmJobFailed(
                    str(exc) or exc.__class__.__name__, classify_error(exc)
                ) from exc
        finally:
            if hasattr(provider, "aclose"):
                await provider.aclose()

        s3_key = raw_bands_key(
            provider_code=product["provider_code"],
            product_code=product["code"],
            scene_id=job["scene_id"],
            aoi_hash=farm["aoi_hash"],
        )
        try:
            storage.put_object(key=s3_key, body=result.cog_bytes, content_type=result.content_type)
        except Exception as exc:
            raise _FarmJobFailed(f"s3_put_failed: {exc}", "storage_error") from exc

        index_keys, stac_item_id, aggregates_written = await _compute_farm_scene_indices(
            tenant_schema=tenant_schema,
            job=job,
            farm=farm,
            product=product,
            storage=storage,
            s3_key=s3_key,
            air_temp_c=farm_air_temp_c,
        )
    except _FarmJobFailed as failure:
        await _fail_farm_job(
            tenant_schema=tenant_schema,
            job_id=job_id,
            farm_id=job["farm_id"],
            error=failure.message,
            error_code=failure.code,
        )
        return {"job_id": str(job_id), "status": "failed"}

    await _record_farm_scene_success(
        tenant_schema=tenant_schema,
        job=job,
        job_id=job_id,
        aoi_hash=farm["aoi_hash"],
        stac_item_id=stac_item_id,
        raw_bands_s3_key=s3_key,
        index_keys=index_keys,
    )

    _log.info(
        "farm_scene_fetched",
        tenant_schema=tenant_schema,
        farm_id=str(job["farm_id"]),
        scene_id=job["scene_id"],
        indices=len(index_keys),
        block_aggregates=aggregates_written,
    )
    return {
        "job_id": str(job_id),
        "status": "succeeded",
        "indices": sorted(index_keys),
        "stac_item_id": stac_item_id,
        "block_aggregates": aggregates_written,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.discover_active_farm_subscriptions",
    bind=False,
    ignore_result=True,
)
def discover_active_farm_subscriptions() -> dict[str, int]:
    """Beat sweep over farms with the farm-AOI fetch switched on.

    Enqueues nothing until a farm sets `fetch_farm_aoi`, so shipping this
    changes no behaviour for anyone.
    """
    return _run_task(_discover_active_farm_subscriptions_async())


async def _discover_active_farm_subscriptions_async() -> dict[str, int]:
    factory = AsyncSessionLocal()
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
        try:
            async with AsyncSessionLocal()() as session2, session2.begin():
                await _set_tenant_context(session2, tenant_schema)
                due = await ImageryRepository(session2).list_farm_subscriptions_due(
                    default_cadence_hours=24,
                    now=datetime.now(UTC),
                    anchor_hour_utc=get_settings().imagery_discovery_anchor_hour_utc,
                )
        except Exception:
            _log.exception("imagery_farm_sweep_tenant_failed", tenant_schema=tenant_schema)
            continue
        for row in due:
            discover_farm_scenes.delay(str(row["id"]), tenant_schema)
            enqueued += 1
    return {"tenants_scanned": len(tenant_schemas), "enqueued": enqueued}


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
    is local to this task â€” keeps the import graph thin for processes
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
        # Read inside the same session as the rest of step 1. Only the
        # thermal product needs it, and only for CWSI.
        air_temp_c = (
            await _air_temp_at_overpass(
                session, farm_id=block["farm_id"], scene_time=job["scene_datetime"]
            )
            if product["code"] == "landsat_c2_l2_st"
            else None
        )

    # Step 2: read raw COG, compute indices, write per-index COGs.
    # Local import â€” pulls rasterio/numpy only into the heavy worker.
    from app.modules.imagery._rasterio_io import (
        compute_and_write_indices,
        load_raw_bands_and_aggregate,
    )

    bucket = storage.bucket
    raw_uri = f"s3://{bucket}/{raw_bands_key_str}"
    # Lineage clock. Started before the raster read so the recorded duration
    # covers the part of this task that can actually be slow.
    calc_started_at = datetime.now(UTC)
    aoi_pixel_count: int | None = None
    masked_pixel_count: int | None = None
    try:
        bands_arrays, aoi_mask, cloud_mask, profile = load_raw_bands_and_aggregate(
            raw_uri,
            band_names=tuple(product["bands"]),
            aoi_geojson_utm=block["boundary_utm_geojson"],
            product_code=product["code"],
        )
        aoi_pixel_count, masked_pixel_count = _mask_counts(aoi_mask, cloud_mask)
        index_aggregates, index_keys, index_rasters = compute_and_write_indices(
            bands_arrays=bands_arrays,
            aoi_mask=aoi_mask,
            cloud_mask=cloud_mask,
            profile=profile,
            storage=storage,
            provider_code=product["provider_code"],
            product_code=product["code"],
            scene_id=job["scene_id"],
            aoi_hash=block["aoi_hash"],
            air_temp_c=air_temp_c,
        )
        raster_transform = profile["transform"]
    except Exception as exc:
        bus.publish(IngestionFailedV1(job_id=job_id, error=f"compute_indices_failed: {exc}"))
        await _record_audit(
            tenant_schema=tenant_schema,
            event_type="imagery.ingestion_failed",
            subject_id=job_id,
            farm_id=block["farm_id"],
            details={"reason": "compute_indices_failed", "error": str(exc)},
        )
        # A failed execution is still an execution, and the fact that it was
        # attempted at all is exactly what a stalled pipeline hides. #335 died
        # nine seconds in and reported nothing, so the console showed a source
        # with no progress and no error.
        await _record_calc_run(
            tenant_schema=tenant_schema,
            job=job,
            block=block,
            product=product,
            grid_config_id=None,
            cell_count=None,
            aoi_pixel_count=aoi_pixel_count,
            masked_pixel_count=masked_pixel_count,
            per_index={},
            outcome="failed",
            error=str(exc)[:1000],
            started_at=calc_started_at,
        )
        return {"job_id": str(job_id), "status": "compute_failed"}

    # Step 3: insert one block_index_aggregates row per index; refresh
    # the pgstac item with merged assets. Also (if this block+product
    # has an active grid_config) populate block_grid_aggregates from
    # the in-memory index rasters via the grid module's zonal helper.
    from app.modules.grid.service import get_grid_service
    from app.modules.grid.zonal import compute_cell_aggregates
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

        # Per-cell aggregates — only if a grid_config exists for this
        # (block, product). Skipped silently otherwise; blocks without
        # cells keep working exactly as before.
        #
        # Resolved by the scene's own time, not "the current grid": this
        # same path runs for historical backfills and late deliveries, and
        # gridding a 2025 scene on a 2026 geometry writes rows no
        # valid-time-aware read can ever return (tenant migration 0054).
        grid_service = get_grid_service(tenant_session=session)
        cells = await grid_service.list_cells_for_scene(
            block_id=job["block_id"],
            product_id=job["product_id"],
            at=job["scene_datetime"],
        )
        if cells:
            per_cell_per_index = _zonal_by_cell(
                cells=cells,
                index_rasters=index_rasters,
                raster_transform=raster_transform,
                compute_cell_aggregates=compute_cell_aggregates,
            )
            await grid_service.record_grid_aggregates(
                scene_time=job["scene_datetime"],
                block_id=job["block_id"],
                product_id=job["product_id"],
                stac_item_id=job["stac_item_id"],
                cloud_cover_pct=job["cloud_cover_pct"],
                per_cell_per_index=per_cell_per_index,
            )
        grid_config_id = cells[0]["grid_config_id"] if cells else None

        # Refresh pgstac.items with the merged asset map.
        from app.modules.imagery.pgstac import (
            build_item_doc,
            collection_id_for,
            upsert_item,
        )

        item_doc = _build_scene_item_doc(
            tenant_schema=tenant_schema,
            job=job,
            block=block,
            product=product,
            bucket=bucket,
            raw_bands_key_str=raw_bands_key_str,
            index_keys=index_keys,
            collection_id_for=collection_id_for,
            build_item_doc=build_item_doc,
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

    # Lineage last, in its own transaction: the aggregates are the product,
    # this is the record of how they were made. Written after the outputs are
    # durable so a lineage failure can never cost a scene its numbers.
    await _record_calc_run(
        tenant_schema=tenant_schema,
        job=job,
        block=block,
        product=product,
        grid_config_id=grid_config_id,
        cell_count=len(cells) if cells else None,
        aoi_pixel_count=aoi_pixel_count,
        masked_pixel_count=masked_pixel_count,
        per_index=_per_index_lineage(index_aggregates, aoi_pixel_count, masked_pixel_count),
        outcome="ok",
        error=None,
        started_at=calc_started_at,
    )

    return {
        "job_id": str(job_id),
        "status": "indices_computed",
        "indices": list(index_aggregates.keys()),
    }


def _zonal_by_cell(
    *,
    cells: Sequence[dict[str, Any]],
    index_rasters: dict[str, Any],
    raster_transform: Any,
    compute_cell_aggregates: Any,
) -> dict[Any, dict[str, Any]]:
    """Zonal statistics for every (cell, index) pair, from the in-memory rasters.

    The zonal helper arrives as an argument for the same reason the pgstac
    helpers do: keep this module's import graph unchanged for processes that
    never compute indices.
    """
    return {
        cell["cell_id"]: {
            index_code: compute_cell_aggregates(
                raster=raster,
                transform=raster_transform,
                cell_polygon_wkt=cell["geom_wkt"],
            )
            for index_code, raster in index_rasters.items()
        }
        for cell in cells
    }


def _build_scene_item_doc(
    *,
    tenant_schema: str,
    job: dict[str, Any],
    block: dict[str, Any],
    product: dict[str, Any],
    bucket: str,
    raw_bands_key_str: str,
    index_keys: dict[str, str],
    collection_id_for: Any,
    build_item_doc: Any,
) -> Any:
    """Merge the raw-bands and per-index assets into one STAC item document.

    Pulled out of the task body purely for size. The pgstac helpers arrive as
    arguments rather than being imported here so the module-level import graph
    stays as it was — this file is loaded by processes that never touch pgstac.
    """
    merged_assets: dict[str, Any] = {
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
    return build_item_doc(
        collection_id=collection_id_for(tenant_schema, product["code"]),
        item_id=job["stac_item_id"],
        geometry_geojson=block["boundary_geojson"],
        bbox=_bbox_from_geojson(block["boundary_geojson"]),
        scene_datetime_iso=_iso(job["scene_datetime"]),
        assets=merged_assets,
        properties={
            "eo:cloud_cover": (
                float(job["cloud_cover_pct"]) if job["cloud_cover_pct"] is not None else None
            ),
            "agripulse:scene_id": job["scene_id"],
            "agripulse:aoi_hash": block["aoi_hash"],
        },
    )


def _mask_counts(aoi_mask: Any, cloud_mask: Any) -> tuple[int, int]:
    """AOI footprint and the cloud-masked share of it.

    The pixel accounting `block_index_aggregates` cannot carry: it holds valid
    and total counts and nothing that separates a cloud-masked pixel from a
    sensor gap, which is why "why is this scene 43% valid?" has no answer in
    the database today. Both masks are already in memory, so this is two
    boolean reductions.
    """
    import numpy as np

    return (
        int(np.count_nonzero(aoi_mask)),
        int(np.count_nonzero(cloud_mask & aoi_mask)),
    )


def _per_index_lineage(
    index_aggregates: dict[str, Any],
    aoi_pixel_count: int | None,
    masked_pixel_count: int | None,
) -> dict[str, Any]:
    """Per-index counts for the lineage row.

    `nodata` is what the aggregate row cannot say: of the pixels inside the
    AOI that survived masking, how many still produced no number — a sensor
    gap, or a divide-by-zero in that index's own formula. It differs per index
    for exactly that second reason.
    """
    return {
        code: {
            "valid": agg.valid_pixel_count,
            "total": agg.total_pixel_count,
            "nodata": max(
                (aoi_pixel_count or 0) - (masked_pixel_count or 0) - agg.valid_pixel_count,
                0,
            ),
            "mean": float(agg.mean) if agg.mean is not None else None,
        }
        for code, agg in index_aggregates.items()
    }


async def _record_calc_run(
    *,
    tenant_schema: str,
    job: dict[str, Any],
    block: dict[str, Any],
    product: dict[str, Any],
    grid_config_id: Any,
    cell_count: int | None,
    aoi_pixel_count: int | None,
    masked_pixel_count: int | None,
    per_index: dict[str, Any],
    outcome: str,
    error: str | None,
    started_at: datetime,
) -> None:
    """Append one `indices_calc_runs` row (tenant migration 0060).

    Best-effort on purpose. Lineage is what lets Observer tell a fresh
    computation from a silent overwrite, but it is *about* the pipeline, not
    part of it — a failure to record the history must never turn a scene that
    computed correctly into a scene that reports as failed.
    """
    from app.modules.indices.service import get_indices_service

    factory = AsyncSessionLocal()
    try:
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            await get_indices_service(tenant_session=session).record_calc_run(
                job_id=job["id"],
                scene_time=job["scene_datetime"],
                scene_id=job["scene_id"],
                stac_item_id=job["stac_item_id"],
                block_id=job["block_id"],
                product_id=job["product_id"],
                aoi_hash=block.get("aoi_hash"),
                grid_config_id=grid_config_id,
                cell_count=cell_count,
                band_order=list(product["bands"]),
                aoi_pixel_count=aoi_pixel_count,
                masked_pixel_count=masked_pixel_count,
                per_index=per_index,
                # Which rules actually ran, not just that some did. Landsat's
                # quality band is a bitmask and Sentinel-2's SCL a class enum,
                # so a row that only said "masked" would be ambiguous between
                # two genuinely different methodologies.
                mask_ruleset=PRODUCT_MASK_RULESETS.get(product["code"], MASK_RULESET),
                # `backfill` vs `live` is not distinguishable from inside this
                # task — both arrive as the same call. The backfill path can
                # start passing its own trigger when it needs to.
                trigger="live",
                outcome=outcome,
                error=error,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
    except Exception as exc:  # lineage must never fail the task
        _log.warning(
            "indices_calc_run_not_recorded",
            tenant_schema=tenant_schema,
            job_id=str(job["id"]),
            error=str(exc)[:300],
        )


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
        # One tenant must not end the sweep for the others — a schema
        # mid-creation or behind on migrations raises here, and without this
        # every remaining tenant silently stops being polled.
        try:
            async with AsyncSessionLocal()() as session2, session2.begin():
                await _set_tenant_context(session2, tenant_schema)
                repo = ImageryRepository(session2)
                due = await repo.list_active_subscriptions_due(
                    default_cadence_hours=24,  # fallback; per-row cadence applies first
                    now=datetime.now(UTC),
                    anchor_hour_utc=get_settings().imagery_discovery_anchor_hour_utc,
                )
        except Exception:
            _log.exception("imagery_due_sweep_tenant_failed", tenant_schema=tenant_schema)
            continue
        for row in due:
            discover_scenes.delay(str(row["id"]), tenant_schema)
            enqueued += 1
    return {"tenants_scanned": len(tenant_schemas), "enqueued": enqueued}


# --- reap_stuck_jobs (Beat sweep) -------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.reap_stuck_jobs",
    bind=False,
    ignore_result=False,
)
def reap_stuck_jobs() -> dict[str, int]:
    """Return jobs stranded in a non-terminal state to `pending` and re-run them.

    A worker that dies between `mark_running` and the terminal write leaves
    the job row in `running`. That row is unreachable afterwards: re-discovery
    hits `ON CONFLICT (subscription_id, scene_id) DO NOTHING`, the re-dispatch
    query reads only `status = 'pending'`, and `acquire_scene` no-ops on
    anything that is not `pending`. The scene is then missing for that block
    for good, which is what production showed on 2026-08-23 — 7 rows in one
    tenant, the oldest 575 hours old, 3 of them with no index rows for a day
    when 35 sibling blocks had a full set.

    Deliberately NOT on the `platform_admins.task_registry` allowlist. It
    walks every active tenant, and that registry's rule is that a
    cross-tenant sweep must never be reachable from a tenant-scoped endpoint.
    The result is kept anyway so a hand-sent run from a worker shell can be
    read back; a reaper that reports nothing is hard to trust.
    """
    return _run_task(_reap_stuck_jobs_async())


async def _reap_stuck_jobs_async() -> dict[str, int]:
    settings = get_settings()
    stuck_hours = settings.imagery_stuck_job_reap_hours
    max_attempts = settings.imagery_stuck_job_max_attempts

    factory = AsyncSessionLocal()
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

    reset_block = 0
    reset_farm = 0
    failed_out = 0
    for tenant_schema in tenant_schemas:
        try:
            sanitize_tenant_schema(tenant_schema)
        except ValueError:
            continue
        # One tenant must not end the sweep for the others. A schema behind
        # on migrations has no `attempts` column and raises here.
        try:
            async with AsyncSessionLocal()() as session2, session2.begin():
                await _set_tenant_context(session2, tenant_schema)
                repo = ImageryRepository(session2)
                for farm_path in (False, True):
                    failed_out += await repo.fail_exhausted_stuck_jobs(
                        stuck_hours=stuck_hours,
                        max_attempts=max_attempts,
                        farm_path=farm_path,
                    )
                block_ids = await repo.reset_stuck_jobs(
                    stuck_hours=stuck_hours, max_attempts=max_attempts, farm_path=False
                )
                farm_ids = await repo.reset_stuck_jobs(
                    stuck_hours=stuck_hours, max_attempts=max_attempts, farm_path=True
                )
        except Exception:
            _log.exception("imagery_reap_tenant_failed", tenant_schema=tenant_schema)
            continue

        # Dispatch outside the transaction, so the worker that picks the job
        # up can see the `pending` row. Same ordering as `discover_scenes`.
        for job_id in block_ids:
            acquire_scene.delay(str(job_id), tenant_schema)
        for job_id in farm_ids:
            acquire_farm_scene.delay(str(job_id), tenant_schema)
        reset_block += len(block_ids)
        reset_farm += len(farm_ids)
        if block_ids or farm_ids or failed_out:
            _log.info(
                "imagery_stuck_jobs_reaped",
                tenant_schema=tenant_schema,
                block_jobs_reset=len(block_ids),
                farm_jobs_reset=len(farm_ids),
            )

    return {
        "tenants_scanned": len(tenant_schemas),
        "block_jobs_reset": reset_block,
        "farm_jobs_reset": reset_farm,
        "jobs_failed_out": failed_out,
    }


# --- publish_farm_boundaries (one-off / on demand) --------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="imagery.publish_farm_boundaries",
    bind=False,
    ignore_result=False,
)
def publish_farm_boundaries(tenant_schema: str | None = None) -> dict[str, int]:
    """Write every farm's outline for the tile server to cut tiles with.

    The compute path publishes a farm's outline with each new scene, so
    this only exists to reach the scenes ALREADY stored: the cut happens
    at render time, so publishing an outline today cuts every pass that
    farm has, back to its first one.

    Pass a tenant schema to do one tenant, or nothing to do them all.
    Safe to run more than once - the object is the same bytes each time.
    """
    return _run_task(_publish_farm_boundaries_async(tenant_schema))


async def _publish_farm_boundaries_async(tenant_schema: str | None) -> dict[str, int]:
    import json as _json

    storage = _get_storage()
    factory = AsyncSessionLocal()

    if tenant_schema:
        tenant_schemas = [tenant_schema]
    else:
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

    written = 0
    skipped = 0
    for schema in tenant_schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        # One tenant must not end the run for the others.
        try:
            async with AsyncSessionLocal()() as session2, session2.begin():
                await _set_tenant_context(session2, schema)
                farms = (
                    await session2.execute(
                        text(
                            """
                            SELECT aoi_hash, ST_AsGeoJSON(boundary)::text AS boundary_geojson
                              FROM farms
                             WHERE deleted_at IS NULL
                               AND aoi_hash IS NOT NULL
                               AND boundary IS NOT NULL
                            """
                        )
                    )
                ).all()
        except Exception:
            _log.exception("aoi_boundary_publish_tenant_failed", tenant_schema=schema)
            continue
        for aoi_hash, boundary_geojson in farms:
            key = publish_aoi_boundary(
                storage,
                aoi_hash=str(aoi_hash),
                boundary_geojson=_json.loads(boundary_geojson),
            )
            if key:
                written += 1
            else:
                skipped += 1

    _log.info(
        "aoi_boundaries_published",
        tenants=len(tenant_schemas),
        written=written,
        skipped=skipped,
    )
    return {"tenants": len(tenant_schemas), "written": written, "skipped": skipped}


# --- helpers ---------------------------------------------------------------


async def _fail_job(
    *,
    tenant_schema: str,
    job_id: UUID,
    farm_id: UUID,
    error: str,
    error_code: str | None = None,
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
            error_code=error_code,
        )
    bus.publish(IngestionFailedV1(job_id=job_id, error=error))
    await _record_audit(
        tenant_schema=tenant_schema,
        event_type="imagery.ingestion_failed",
        subject_id=job_id,
        farm_id=farm_id,
        details={"error": error},
    )


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bbox_from_geojson(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    """Compute a 2D bbox from a GeoJSON Polygon/MultiPolygon.

    The block boundary is always a Polygon (data_model Â§ 5.5); guard
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
