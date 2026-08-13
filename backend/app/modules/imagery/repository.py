"""Async DB access for the imagery module. Internal to the module.

Reads/writes for `imagery_aoi_subscriptions` and `imagery_ingestion_jobs`,
plus a couple of helpers the Celery tasks use to look up the block's
boundary + aoi_hash without crossing the farms-module boundary in SQL
(we go through one tenant-scoped session and read `blocks` directly —
ARCHITECTURE.md § 6.1 forbids importing another module's *internals*,
not reading shared schema rows the other module owns).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, bindparam, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.errors import (
    IngestionJobNotFoundError,
    SubscriptionAlreadyExistsError,
    SubscriptionNotFoundError,
)
from app.modules.imagery.models import (
    ImageryAoiSubscription,
    ImageryIngestionJob,
)


class ImageryRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Subscriptions -------------------------------------------------

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        clauses = [ImageryAoiSubscription.block_id == block_id]
        if not include_inactive:
            clauses.append(ImageryAoiSubscription.is_active.is_(True))
        clauses.append(ImageryAoiSubscription.deleted_at.is_(None))
        rows = (
            (
                await self._session.execute(
                    select(ImageryAoiSubscription)
                    .where(and_(*clauses))
                    .order_by(ImageryAoiSubscription.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return tuple(_subscription_to_dict(r) for r in rows)

    async def get_subscription(self, subscription_id: UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(ImageryAoiSubscription).where(
                    and_(
                        ImageryAoiSubscription.id == subscription_id,
                        ImageryAoiSubscription.deleted_at.is_(None),
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise SubscriptionNotFoundError(str(subscription_id))
        return _subscription_to_dict(row)

    async def list_active_subscriptions_due(
        self,
        *,
        default_cadence_hours: int,
        now: datetime,
    ) -> tuple[dict[str, Any], ...]:
        """Return active subscriptions whose `last_attempted_at` is older
        than their cadence (or NULL — never attempted).

        ``cadence_hours`` defaults to ``default_cadence_hours`` when the
        column is NULL. The Beat sweep enqueues a `discover_scenes`
        task per result.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT * FROM imagery_aoi_subscriptions
                    WHERE is_active = TRUE
                      AND deleted_at IS NULL
                      AND (
                            last_attempted_at IS NULL
                         OR last_attempted_at <
                            (:now - make_interval(
                                hours => COALESCE(cadence_hours, :default_cadence)
                            ))
                      )
                    ORDER BY created_at ASC
                    """
                    ).bindparams(now=now, default_cadence=default_cadence_hours)
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def insert_subscription(
        self,
        *,
        subscription_id: UUID,
        block_id: UUID,
        product_id: UUID,
        cadence_hours: int | None,
        cloud_cover_max_pct: int | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        from sqlalchemy.exc import IntegrityError  # local — narrow import

        row = ImageryAoiSubscription(
            id=subscription_id,
            block_id=block_id,
            product_id=product_id,
            cadence_hours=cadence_hours,
            cloud_cover_max_pct=cloud_cover_max_pct,
            is_active=True,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # The partial UNIQUE on (block_id, product_id) WHERE is_active
            # — re-raise as a domain conflict.
            raise SubscriptionAlreadyExistsError() from exc
        return _subscription_to_dict(row)

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        before = await self.get_subscription(subscription_id)
        if not before["is_active"]:
            return before  # already revoked — idempotent
        await self._session.execute(
            update(ImageryAoiSubscription)
            .where(ImageryAoiSubscription.id == subscription_id)
            .values(is_active=False, updated_by=actor_user_id)
        )
        await self._session.flush()
        return await self.get_subscription(subscription_id)

    async def reset_last_successful_for_block(self, block_id: UUID) -> int:
        """Set `last_successful_ingest_at = NULL` on every active subscription
        of the block — called by the BlockBoundaryChangedV1 subscriber so
        the next discovery refetches against the new aoi_hash.

        Returns the number of rows updated; tests assert on this count.
        """
        result = await self._session.execute(
            update(ImageryAoiSubscription)
            .where(
                and_(
                    ImageryAoiSubscription.block_id == block_id,
                    ImageryAoiSubscription.is_active.is_(True),
                    ImageryAoiSubscription.deleted_at.is_(None),
                )
            )
            .values(last_successful_ingest_at=None)
        )
        await self._session.flush()
        # SQLAlchemy 2.x: Result for non-DML defines no rowcount; for an
        # UPDATE the underlying CursorResult does. Cast through the
        # `_attr` descriptor explicitly to satisfy mypy strict.
        rowcount = getattr(result, "rowcount", 0)
        return int(rowcount or 0)

    async def touch_subscription_attempt(
        self,
        *,
        subscription_id: UUID,
        attempted_at: datetime,
        ingested: bool,
    ) -> None:
        """Record a discovery poll against the subscription.

        `last_attempted_at` is the wall-clock heartbeat — it advances on
        *every* completed poll (success or not) and is what the
        integration-health "overdue" check keys off, since polling on
        cadence is the part we control. `last_successful_ingest_at`
        advances only when the poll actually queued usable imagery; it is
        the discovery-window watermark and the honest "last imagery we
        pulled" signal. Conflating the two (the pre-fix behaviour) bumped
        the watermark on every empty poll, which both hid genuine staleness
        and let publication-lagged scenes slip behind the watermark.
        """
        values: dict[str, Any] = {"last_attempted_at": attempted_at}
        if ingested:
            values["last_successful_ingest_at"] = attempted_at
        await self._session.execute(
            update(ImageryAoiSubscription)
            .where(ImageryAoiSubscription.id == subscription_id)
            .values(**values)
        )

    # ---- Ingestion jobs -----------------------------------------------

    async def list_farm_scene_days(
        self,
        *,
        farm_id: UUID,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        """Acquisition days for a whole farm, newest first, in one statement.

        The console's scene strip spans the farm, and the only route to that
        today is one ``/blocks/{id}/scenes`` call per block — 36 requests on
        the reference farm, which is the same fan-out that took the
        connection pool down in #311 and that the farm-level grid route was
        added to remove. One aggregate query instead.

        Grouped by day: blocks in different tiles carry slightly different
        sensing times for one pass, and the grower's unit is the day.

        Note this reads ingestion JOBS, not observations — a pass that was
        skipped for cloud still produced a job row, and the strip has to show
        it. A gap the user can see and understand ("cloudy") is worth far
        more than a silently shorter timeline.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            (j.scene_datetime AT TIME ZONE 'UTC')::date AS scene_date,
                            max(j.scene_datetime)                       AS at,
                            count(DISTINCT j.block_id)                  AS block_count,
                            count(*) FILTER (
                                WHERE j.status = 'succeeded'
                            )                                           AS succeeded_count,
                            count(*) FILTER (
                                WHERE j.status = 'skipped_cloud'
                            )                                           AS skipped_cloud_count,
                            count(DISTINCT a.block_id)                  AS computed_count,
                            avg(j.cloud_cover_pct)                      AS cloud_cover_pct
                        FROM imagery_ingestion_jobs j
                        JOIN blocks b ON b.id = j.block_id
                        -- Did the INDEX step ever run for this pass?
                        --
                        -- Ingesting a scene and computing its indices are two
                        -- different tasks, and a historical backfill runs the
                        -- first without the second (`run_compute_indices:
                        -- False` in the backfill service). The job row then
                        -- says "succeeded" and carries a stac_item_id while no
                        -- index raster was ever written — 104 of 131 days on
                        -- the reference farm are in exactly that state.
                        --
                        -- An aggregate row is written by `compute_indices` and
                        -- by nothing else, so its presence is the only honest
                        -- answer to "can this pass be drawn?". Without it the
                        -- console offers a date that renders nothing.
                        LEFT JOIN block_index_aggregates a
                               ON a.block_id = j.block_id
                              AND a.time = j.scene_datetime
                              AND a.index_code = 'ndvi'
                        WHERE b.farm_id = :farm
                        GROUP BY 1
                        ORDER BY 1 DESC
                        LIMIT :limit
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_farm_scene_assets(
        self,
        *,
        farm_id: UUID,
        at: datetime | None,
    ) -> tuple[dict[str, Any], ...]:
        """One row per block: the index asset to render for a given pass.

        The console paints index PIXELS, and a pixel layer needs the COG's
        object key — which is derivable from ``stac_item_id``
        (``provider/product/scene/aoi``) and nothing else. Without this route
        the frontend would have to ask ``/blocks/{id}/scenes`` per block to
        find it: the same 36-request fan-out that ``/farms/{id}/scenes`` and
        ``/farms/{id}/grid-cells`` both exist to avoid.

        ``at`` is the timeline's scene bound (end of the acquisition day), so
        each block resolves to ITS OWN latest pass at or before that instant.
        Blocks in different tiles are sensed minutes apart for what a grower
        calls one pass, and pinning every block to a single timestamp would
        drop whichever block was sensed a minute later.

        Only ``succeeded`` jobs are eligible, and that is the whole guard:
        ``mark_succeeded`` is what sets ``stac_item_id`` in the first place,
        so a job in any other state either has no key or has one pointing at
        assets that were never written. A cloud-skipped pass in particular
        still leaves a job row — it belongs on the timeline, but pointing the
        tile server at it would 404 every tile and paint an empty block.

        ``resolution_m`` rides along because the legend turns a pixel COUNT
        into an AREA, and fetching the product's resolution separately would
        be one more request for a number this row already knows.
        """
        clauses = ["b.farm_id = :farm", "j.stac_item_id IS NOT NULL", "j.status = 'succeeded'"]
        params: dict[str, Any] = {"farm": farm_id}
        if at is not None:
            clauses.append("j.scene_datetime <= :at")
            params["at"] = at
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT DISTINCT ON (j.block_id)
                            j.block_id,
                            j.product_id,
                            j.stac_item_id,
                            j.scene_datetime,
                            p.resolution_m
                        FROM imagery_ingestion_jobs j
                        JOIN blocks b ON b.id = j.block_id
                        -- public, and LEFT: products are cross-schema (the
                        -- tenant carries only a logical id), and a product row
                        -- we cannot read must cost the caller a resolution,
                        -- not the whole block's imagery.
                        LEFT JOIN public.imagery_products p ON p.id = j.product_id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY j.block_id, j.scene_datetime DESC
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_farm_scene_sources(
        self,
        *,
        farm_id: UUID,
        scene_datetime: datetime,
    ) -> dict[str, Any] | None:
        """Everything needed to stitch one farm-wide raster for one pass.

        Returns the farm's own AOI hash plus every block job of that pass that
        actually wrote raw bands — the inputs the merge consumes. ``None`` when
        the farm has no usable job for the instant, which the caller treats as
        "nothing to build" rather than as an error.

        Jobs are matched on the exact ``scene_datetime`` rather than the day:
        blocks in different Sentinel tiles are sensed minutes apart, and a
        day-wide match would merge two passes into one surface.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            j.block_id,
                            j.product_id,
                            j.stac_item_id,
                            j.scene_id,
                            j.scene_datetime,
                            f.aoi_hash AS farm_aoi_hash
                        FROM imagery_ingestion_jobs j
                        JOIN blocks b ON b.id = j.block_id
                        JOIN farms f ON f.id = b.farm_id
                        WHERE b.farm_id = :farm
                          AND j.scene_datetime = :at
                          AND j.status = 'succeeded'
                          AND j.stac_item_id IS NOT NULL
                        ORDER BY j.block_id
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id, "at": scene_datetime},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        first = rows[0]
        if first["farm_aoi_hash"] is None:
            # Pre-0073 farm row that the backfill missed; refusing here beats
            # writing rasters under an empty prefix that nothing can find.
            return None
        return {
            "farm_aoi_hash": first["farm_aoi_hash"],
            "product_id": first["product_id"],
            "scene_id": first["scene_id"],
            "scene_datetime": first["scene_datetime"],
            "stac_item_ids": [r["stac_item_id"] for r in rows],
            "block_ids": [r["block_id"] for r in rows],
        }

    async def list_farm_scene_instants(
        self,
        *,
        farm_id: UUID,
        limit: int,
    ) -> tuple[datetime, ...]:
        """Distinct sensing instants for a farm, newest first.

        The rebuild walks these: one farm raster per instant. Distinct on the
        exact instant, not the day, for the same reason the source query is.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT DISTINCT j.scene_datetime
                    FROM imagery_ingestion_jobs j
                    JOIN blocks b ON b.id = j.block_id
                    WHERE b.farm_id = :farm
                      AND j.status = 'succeeded'
                      AND j.stac_item_id IS NOT NULL
                    ORDER BY j.scene_datetime DESC
                    LIMIT :limit
                    """
                ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                {"farm": farm_id, "limit": limit},
            )
        ).all()
        return tuple(r[0] for r in rows)

    async def record_farm_scene_raster(
        self,
        *,
        farm_id: UUID,
        product_id: UUID,
        scene_datetime: datetime,
        scene_id: str,
        stac_item_id: str,
        aoi_hash: str,
        blocks_merged: int,
        indices: list[str],
    ) -> None:
        """Note that a farm-wide raster now exists for this pass.

        Upsert on (farm, pass, boundary): rebuilding a pass replaces the row
        rather than accumulating history nobody reads. The row is what lets the
        API answer "is there a farm raster here?" without probing the bucket,
        and what makes the cutover per farm — a farm with rows serves one
        raster, a farm without keeps the per-block path untouched.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO farm_scene_rasters (
                    farm_id, product_id, scene_datetime, scene_id,
                    stac_item_id, aoi_hash, blocks_merged, indices
                )
                VALUES (
                    :farm, :product, :at, :scene_id,
                    :stac, :aoi_hash, :blocks, CAST(:indices AS jsonb)
                )
                ON CONFLICT (farm_id, scene_datetime, aoi_hash) DO UPDATE
                SET stac_item_id  = EXCLUDED.stac_item_id,
                    product_id    = EXCLUDED.product_id,
                    scene_id      = EXCLUDED.scene_id,
                    blocks_merged = EXCLUDED.blocks_merged,
                    indices       = EXCLUDED.indices,
                    built_at      = now()
                """
            ).bindparams(
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("product", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "farm": farm_id,
                "product": product_id,
                "at": scene_datetime,
                "scene_id": scene_id,
                "stac": stac_item_id,
                "aoi_hash": aoi_hash,
                "blocks": blocks_merged,
                "indices": json.dumps(indices),
            },
        )

    async def get_farm_scene_raster(
        self,
        *,
        farm_id: UUID,
        at: datetime | None,
    ) -> dict[str, Any] | None:
        """The farm-wide raster to draw for a pass, or None if there is none.

        Matched against the farm's CURRENT aoi_hash: a farm reshaped since the
        raster was stitched falls back to the per-block path rather than
        drawing a surface cut to a boundary that no longer exists.
        """
        clauses = ["r.farm_id = :farm", "r.aoi_hash = f.aoi_hash"]
        params: dict[str, Any] = {"farm": farm_id}
        if at is not None:
            clauses.append("r.scene_datetime <= :at")
            params["at"] = at
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT r.scene_datetime, r.stac_item_id, r.product_id,
                               r.blocks_merged, p.resolution_m
                        FROM farm_scene_rasters r
                        JOIN farms f ON f.id = r.farm_id
                        LEFT JOIN public.imagery_products p ON p.id = r.product_id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY r.scene_datetime DESC
                        LIMIT 1
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return dict(rows[0]) if rows else None

    async def list_ingestion_jobs_for_block(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None,
        to_datetime: datetime | None,
        cursor: datetime | None,
        limit: int,
    ) -> tuple[tuple[dict[str, Any], ...], datetime | None]:
        """Cursor-paginated by scene_datetime (DESC).

        Cursor is the last seen scene_datetime; the next page asks for
        rows strictly older. Returns ``(items, next_cursor)`` —
        ``next_cursor`` is None on the last page.
        """
        clauses = ["block_id = :block_id"]
        params: dict[str, Any] = {"block_id": block_id}
        if from_datetime is not None:
            clauses.append("scene_datetime >= :from_dt")
            params["from_dt"] = from_datetime
        if to_datetime is not None:
            clauses.append("scene_datetime <= :to_dt")
            params["to_dt"] = to_datetime
        if cursor is not None:
            clauses.append("scene_datetime < :cursor")
            params["cursor"] = cursor
        params["limit"] = limit + 1  # over-fetch by one to detect next page
        where_sql = " AND ".join(clauses)
        # `where_sql` is composed from a closed set of column names below;
        # every value bind goes through SQLAlchemy `text(...)` parameters.
        sql = " ".join(
            (
                "SELECT id, subscription_id, block_id, product_id, scene_id,",
                "scene_datetime, requested_at, started_at, completed_at,",
                "status, cloud_cover_pct, valid_pixel_pct, error_message,",
                "stac_item_id, assets_written",
                "FROM imagery_ingestion_jobs",
                "WHERE",
                where_sql,
                "ORDER BY scene_datetime DESC",
                "LIMIT :limit",
            )
        )
        rows = (
            (
                await self._session.execute(
                    text(sql).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        items = [dict(r) for r in rows]
        next_cursor: datetime | None = None
        if len(items) > limit:
            # Drop the over-fetched row and emit its predecessor as the cursor.
            items = items[:limit]
            next_cursor = items[-1]["scene_datetime"]
        return tuple(items), next_cursor

    async def list_products(self) -> tuple[dict[str, Any], ...]:
        """Read public.imagery_products joined with the provider for /api/v1/config."""
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT pr.id AS product_id, pr.code AS product_code, "
                        "pr.name AS product_name, pr.bands, pr.supported_indices, "
                        "p.code AS provider_code "
                        "FROM public.imagery_products pr "
                        "JOIN public.imagery_providers p ON p.id = pr.provider_id "
                        "WHERE pr.is_active = TRUE AND pr.deleted_at IS NULL "
                        "  AND p.is_active = TRUE "
                        "ORDER BY pr.code"
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def get_ingestion_job(self, job_id: UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(ImageryIngestionJob).where(ImageryIngestionJob.id == job_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise IngestionJobNotFoundError(str(job_id))
        return _ingestion_job_to_dict(row)

    async def upsert_pending_ingestion_job(
        self,
        *,
        job_id: UUID,
        subscription_id: UUID,
        block_id: UUID,
        product_id: UUID,
        scene_id: str,
        scene_datetime: datetime,
        cloud_cover_pct: Decimal | None,
    ) -> tuple[UUID, bool]:
        """Insert a `pending` job; return (job_id, created).

        Idempotency key per data_model § 6.5 is
        ``UNIQUE(subscription_id, scene_id)``. Re-discovering the same
        scene must NOT spawn another row — return the existing id and
        ``created=False``.
        """
        result = await self._session.execute(
            text(
                """
                INSERT INTO imagery_ingestion_jobs (
                    id, subscription_id, block_id, product_id, scene_id,
                    scene_datetime, cloud_cover_pct, status, requested_at
                )
                VALUES (
                    :id, :subscription_id, :block_id, :product_id, :scene_id,
                    :scene_datetime, :cloud_cover_pct, 'pending', now()
                )
                ON CONFLICT (subscription_id, scene_id) DO NOTHING
                RETURNING id
                """
            ).bindparams(),
            {
                "id": job_id,
                "subscription_id": subscription_id,
                "block_id": block_id,
                "product_id": product_id,
                "scene_id": scene_id,
                "scene_datetime": scene_datetime,
                "cloud_cover_pct": cloud_cover_pct,
            },
        )
        inserted = result.scalar()
        if inserted is not None:
            return UUID(str(inserted)), True
        # Existing row — fetch its id and return.
        existing = (
            await self._session.execute(
                text(
                    "SELECT id FROM imagery_ingestion_jobs "
                    "WHERE subscription_id = :s AND scene_id = :sc"
                ),
                {"s": subscription_id, "sc": scene_id},
            )
        ).scalar_one()
        return UUID(str(existing)), False

    async def mark_running(self, *, job_id: UUID, started_at: datetime) -> None:
        await self._session.execute(
            update(ImageryIngestionJob)
            .where(ImageryIngestionJob.id == job_id)
            .values(status="running", started_at=started_at)
        )
        await self._session.flush()

    async def mark_succeeded(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        stac_item_id: str,
        assets_written: list[str],
        valid_pixel_pct: Decimal | None = None,
    ) -> None:
        await self._session.execute(
            update(ImageryIngestionJob)
            .where(ImageryIngestionJob.id == job_id)
            .values(
                status="succeeded",
                completed_at=completed_at,
                stac_item_id=stac_item_id,
                assets_written=assets_written,
                valid_pixel_pct=valid_pixel_pct,
            )
        )
        await self._session.flush()

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        error_message: str,
        error_code: str | None = None,
    ) -> None:
        """Transition a running job to 'failed'.

        `error_code` is the short categorized label
        (`tls_trust`, `timeout`, `http_5xx`, …). When None the column
        stays NULL — caller didn't know how to classify the failure
        and the Runs tab will group it under "uncategorized".
        """
        values: dict[str, Any] = {
            "status": "failed",
            "completed_at": completed_at,
            "error_message": error_message[:1000],
        }
        if error_code is not None:
            values["error_code"] = error_code[:64]
        await self._session.execute(
            update(ImageryIngestionJob).where(ImageryIngestionJob.id == job_id).values(**values)
        )
        await self._session.flush()

    async def mark_skipped(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        reason: str,
    ) -> None:
        """`reason` ∈ {'cloud','duplicate','out_of_window'}; the column
        constraint accepts only the two `skipped_*` statuses, so the
        caller maps the reason → status here.
        """
        status_map = {
            "cloud": "skipped_cloud",
            "duplicate": "skipped_duplicate",
            # 'out_of_window' is a reason for *not* creating a job at
            # all rather than marking one — kept here for symmetry with
            # SceneSkippedV1's reason vocabulary.
            "out_of_window": "skipped_duplicate",
        }
        await self._session.execute(
            update(ImageryIngestionJob)
            .where(ImageryIngestionJob.id == job_id)
            .values(status=status_map[reason], completed_at=completed_at)
        )
        await self._session.flush()

    async def get_block_boundary(self, block_id: UUID) -> dict[str, Any] | None:
        """Read `boundary`, `boundary_utm`, `aoi_hash`, `farm_id` for a block.

        Returns None if the block is missing or soft-deleted. Used by
        the discovery / fetch path so it can build the SH AOI without
        importing from `app.modules.farms`.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT
                        b.farm_id,
                        b.aoi_hash,
                        ST_AsGeoJSON(b.boundary)::text AS boundary_geojson,
                        ST_AsGeoJSON(b.boundary_utm)::text AS boundary_utm_geojson
                    FROM blocks b
                    WHERE b.id = :id AND b.deleted_at IS NULL
                    """
                    ),
                    {"id": block_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "farm_id": row["farm_id"],
            "aoi_hash": row["aoi_hash"],
            "boundary_geojson": json.loads(row["boundary_geojson"]),
            "boundary_utm_geojson": json.loads(row["boundary_utm_geojson"]),
        }


# ---- Row → dict projections ----------------------------------------------


def _subscription_to_dict(row: ImageryAoiSubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "block_id": row.block_id,
        "product_id": row.product_id,
        "cadence_hours": row.cadence_hours,
        "cloud_cover_max_pct": row.cloud_cover_max_pct,
        "is_active": row.is_active,
        "last_successful_ingest_at": row.last_successful_ingest_at,
        "last_attempted_at": row.last_attempted_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _ingestion_job_to_dict(row: ImageryIngestionJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "block_id": row.block_id,
        "product_id": row.product_id,
        "scene_id": row.scene_id,
        "scene_datetime": row.scene_datetime,
        "requested_at": row.requested_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "status": row.status,
        "cloud_cover_pct": row.cloud_cover_pct,
        "valid_pixel_pct": row.valid_pixel_pct,
        "error_message": row.error_message,
        "stac_item_id": row.stac_item_id,
        "assets_written": row.assets_written,
    }


# Suppress unused-import noise on the optional types.
_: tuple[Any, ...] = (PG_UUID, JSONB)
