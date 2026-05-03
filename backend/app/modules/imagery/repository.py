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
        success: bool,
    ) -> None:
        values: dict[str, Any] = {"last_attempted_at": attempted_at}
        if success:
            values["last_successful_ingest_at"] = attempted_at
        await self._session.execute(
            update(ImageryAoiSubscription)
            .where(ImageryAoiSubscription.id == subscription_id)
            .values(**values)
        )

    # ---- Ingestion jobs -----------------------------------------------

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
    ) -> None:
        await self._session.execute(
            update(ImageryIngestionJob)
            .where(ImageryIngestionJob.id == job_id)
            .values(
                status="failed",
                completed_at=completed_at,
                error_message=error_message[:1000],
            )
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
