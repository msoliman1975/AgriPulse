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
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, Text, and_, bindparam, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
from app.shared.db.ids import uuid7


def _utc_day_start(at: datetime) -> datetime:
    """Midnight UTC of the acquisition day ``at`` falls in.

    The scene strip groups passes by ``(scene_datetime AT TIME ZONE 'UTC')
    ::date`` and hands back one instant per day, so UTC is the only day
    boundary that agrees with the dates the console is showing. Computed in
    Python and bound as a real datetime rather than expressed as a SQL cast,
    because a postfix cast on a bind parameter inside ``text()`` is how this
    codebase has broken production three times over.
    """
    return (
        (at if at.tzinfo else at.replace(tzinfo=UTC))
        .astimezone(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )


# The farm scene strip, in one statement. See
# `ImageryRepository.list_farm_scene_days` for what each branch means.
#
# Module-level so `test_farm_scene_strip_plan.py` can EXPLAIN the exact SQL
# that ships. This query's cost lives in its PLAN SHAPE, not in its results,
# and no assertion on the rows it returns can see that — which is precisely
# how the 32 s version passed a full suite of behavioural tests.
_FARM_SCENE_DAYS_SQL = """
WITH live_blocks AS (
    SELECT count(*)::bigint AS n
      FROM blocks b
     WHERE b.farm_id = :farm
       AND b.deleted_at IS NULL
       AND (b.active_to IS NULL OR b.active_to > now())
),
block_days AS (
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
        avg(j.cloud_cover_pct)                      AS cloud_cover_pct,
        -- How much of the farm this pass could NOT measure. See the note on
        -- `no_reading_pct` under the outer SELECT for why the job's own
        -- `cloud_cover_pct` cannot answer this.
        CASE
            WHEN sum(a.total_pixel_count) > 0
            THEN round(
                100.0 * (sum(a.total_pixel_count) - sum(a.valid_pixel_count))
                / sum(a.total_pixel_count),
                2
            )
        END                                         AS no_reading_pct
    FROM imagery_ingestion_jobs j
    JOIN blocks b ON b.id = j.block_id
    -- Did the INDEX step ever run for this pass?
    --
    -- Ingesting a scene and computing its indices are two different tasks,
    -- and a historical backfill runs the first without the second
    -- (`run_compute_indices: False` in the backfill service). The job row
    -- then says "succeeded" and carries a stac_item_id while no index raster
    -- was ever written — 104 of 131 days on the reference farm are in
    -- exactly that state.
    --
    -- An aggregate row is written by `compute_indices` and by nothing else,
    -- so its presence is the only honest answer to "can this pass be drawn?".
    -- Without it the console offers a date that renders nothing.
    --
    -- Tested against the index the caller is ABOUT TO DRAW, not a hardcoded
    -- `ndvi`. A thermal pass writes lst/cwsi/smi and never ndvi, so the
    -- hardcoded form marked every thermal pass unprocessed forever — and the
    -- strip is what SELECTS a pass, so the index could not be drawn at all.
    LEFT JOIN block_index_aggregates a
           ON a.block_id = j.block_id
          AND a.time = j.scene_datetime
          AND a.index_code = :index_code
    -- public, and INNER: the product code is what scopes this pass to the
    -- index being drawn, so a product row we cannot read must drop the pass
    -- rather than admit it unscoped.
    JOIN public.imagery_products jp ON jp.id = j.product_id
    WHERE b.farm_id = :farm
      AND jp.code IN :product_codes
    GROUP BY 1
),
farm_passes AS (
    SELECT
        (fj.scene_datetime AT TIME ZONE 'UTC')::date AS scene_date,
        max(fj.scene_datetime)                       AS at,
        bool_or(fj.status = 'succeeded')             AS any_succeeded,
        bool_or(fj.status = 'skipped')               AS any_skipped,
        avg(fj.cloud_cover_pct)                      AS cloud_cover_pct
    FROM imagery_farm_ingestion_jobs fj
    JOIN public.imagery_products fp ON fp.id = fj.product_id
    WHERE fj.farm_id = :farm
      AND fp.code IN :product_codes
    GROUP BY 1
),
-- Matched on the exact instant, the same way the block branch is, and
-- specifically on the farm pass's `at` — the instant the frontend goes on to
-- send as `at` for grid-cells and scene assets. So "can this pass be drawn?"
-- is answered about the pass it will actually ask for.
--
-- Set-based ON PURPOSE. This started life as a correlated subquery per
-- farm-pass day. Same predicate, same rows, different order of magnitude:
-- the correlated `at` is only known at run time, so TimescaleDB cannot
-- exclude chunks at PLAN time and falls back to RUNTIME exclusion — re-done
-- on every loop. Green Farm [Demo-01] has 52 farm-pass days and
-- `block_index_aggregates` carries 495 chunks (62k rows, ~125 rows per chunk
-- — migration 0057 widened the interval for NEW chunks only), so the strip
-- paid ~26k chunk-exclusion evaluations to return 52 rows: 32.0 s measured
-- on prod, of which only 462 ms was actual row work. The plan was 3,629
-- lines and 964 chunk scan nodes.
--
-- Grouping once and joining back reads the hypertable a single time:
-- 32.0 s -> 380 ms, verified on prod with EXCEPT ALL both ways against the
-- correlated version on a farm-path farm and a block-path farm, 0 rows
-- differing either way.
--
-- The cost scales with PASS DAYS, not blocks, so the 4-block farm was 47x
-- slower than the 36-block one. Keep this branch set-based.
farm_agg AS (
    SELECT
        a.time                     AS at,
        count(DISTINCT a.block_id) AS computed_count,
        CASE
            WHEN sum(a.total_pixel_count) > 0
            THEN round(
                100.0 * (sum(a.total_pixel_count) - sum(a.valid_pixel_count))
                / sum(a.total_pixel_count),
                2
            )
        END                        AS no_reading_pct
    FROM block_index_aggregates a
    JOIN blocks ab ON ab.id = a.block_id
    WHERE ab.farm_id = :farm
      AND a.index_code = :index_code
      AND a.time IN (SELECT at FROM farm_passes)
    GROUP BY a.time
),
farm_days AS (
    SELECT
        p.scene_date,
        p.at,
        l.n AS block_count,
        CASE WHEN p.any_succeeded
             THEN l.n ELSE 0::bigint END AS succeeded_count,
        CASE WHEN p.any_skipped
             THEN l.n ELSE 0::bigint END AS skipped_cloud_count,
        -- LEFT JOIN + COALESCE, not JOIN: a pass whose indices never ran has
        -- no row in `farm_agg` and must still surface as a day with
        -- computed_count 0 — the strip greys it out as unprocessed — exactly
        -- as count() over no rows did.
        COALESCE(g.computed_count, 0::bigint) AS computed_count,
        p.cloud_cover_pct,
        -- No COALESCE here, unlike computed_count: a pass whose indices never
        -- ran measured no pixels at all, and "0% unreadable" would be a claim
        -- about a map that does not exist. NULL is the honest answer.
        g.no_reading_pct
    FROM farm_passes p
    CROSS JOIN live_blocks l
    LEFT JOIN farm_agg g ON g.at = p.at
)
SELECT
    scene_date,
    max(at)                  AS at,
    max(block_count)         AS block_count,
    max(succeeded_count)     AS succeeded_count,
    max(skipped_cloud_count) AS skipped_cloud_count,
    max(computed_count)      AS computed_count,
    avg(cloud_cover_pct)     AS cloud_cover_pct,
    -- The share of the farm this pass left with no reading, measured from the
    -- pixels the index step actually counted.
    --
    -- `cloud_cover_pct` cannot stand in for it. That number is the STAC
    -- `eo:cloud_cover` of a whole Sentinel-2 tile — 110 km on a side against a
    -- farm of 50 ha — so it describes weather somewhere in the tile, not over
    -- this farm. Measured on Green Farm [Demo-01]: 2026-08-17 reports 13.24%
    -- cloud and left every cell readable, while 2026-08-18 reports 6.50% and
    -- blanked 84 of AG-R02-C02's 224 cells. Ranking the two by the tile figure
    -- puts them in the wrong order, so putting it on the strip would point the
    -- reader at the wrong day.
    --
    -- `valid_pixel_count` and `total_pixel_count` are per farm, per pass and
    -- per index, written by the same step that writes the pixels the console
    -- draws. On the same two days they read 2.0% and 8.2%.
    --
    -- On a cutover day both branches measure the same ground; take the worse
    -- of the two rather than mixing a numerator from one with a denominator
    -- from the other. Never claim the map is more complete than it is.
    max(no_reading_pct)      AS no_reading_pct
FROM (
    SELECT * FROM block_days
    UNION ALL
    SELECT * FROM farm_days
) u
GROUP BY scene_date
ORDER BY scene_date DESC
LIMIT :limit
"""


def _due_predicate_sql(prefix: str = "") -> str:
    """SQL for "this subscription should be polled now".

    Two ways to become due, joined by OR:

    1. The plain cadence rule — the last attempt is older than
       ``cadence_hours`` (or there has never been one).
    2. The daily anchor — for a subscription on a cadence of a day or more,
       once the clock passes ``:anchor_hour`` UTC and the last attempt was
       before today's anchor.

    Rule 2 exists because rule 1 alone anchors a daily poll wherever the
    previous one landed and keeps it there. A farm whose poll drifted to
    03:23 UTC kept missing the same day's Sentinel-2 scene, published at
    12:30 UTC, and served three-day-old imagery while a fresh scene sat in
    the catalogue (measured on prod, Agrosina, 2026-08-20).

    The two rules converge rather than compete. After an anchor-triggered
    poll, ``last_attempted_at`` is today's anchor time, so rule 1 next fires
    24h later — which is the anchor again. A daily subscription therefore
    settles into exactly one poll per day, at the anchor hour.

    Both anchor comparisons pin the day boundary to UTC explicitly rather
    than trusting the session's TimeZone setting.

    ``prefix`` is the table alias plus a dot, or empty for an unaliased table.
    """
    p = prefix
    anchor = (
        "(date_trunc('day', :now AT TIME ZONE 'UTC') "
        "+ make_interval(hours => :anchor_hour)) AT TIME ZONE 'UTC'"
    )
    return f"""(
            {p}last_attempted_at IS NULL
         OR {p}last_attempted_at <
            (:now - make_interval(
                hours => COALESCE({p}cadence_hours, :default_cadence)
            ))
         OR (
                :anchor_hour IS NOT NULL
            AND COALESCE({p}cadence_hours, :default_cadence) >= 24
            AND :now >= {anchor}
            AND {p}last_attempted_at < {anchor}
            )
      )"""


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
        anchor_hour_utc: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return active subscriptions that are due to be polled.

        ``cadence_hours`` defaults to ``default_cadence_hours`` when the
        column is NULL. ``anchor_hour_utc`` adds the daily anchor rule — see
        `_due_predicate_sql`. The Beat sweep enqueues a `discover_scenes`
        task per result.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                    SELECT s.* FROM imagery_aoi_subscriptions s
                    WHERE s.is_active = TRUE
                      AND s.deleted_at IS NULL
                      AND {_due_predicate_sql("s.")}
                      -- Skip blocks whose FARM is being fetched as one AOI.
                      -- Gated on fetch_farm_aoi, not merely on a farm row
                      -- existing: 0074 created a farm subscription for every
                      -- farm that had block ones, so keying off existence
                      -- alone would stop imagery platform-wide the moment
                      -- this shipped. Only a farm actually switched over
                      -- stops fetching per block.
                      AND NOT EXISTS (
                          SELECT 1
                          FROM imagery_farm_subscriptions f
                          JOIN blocks b ON b.id = s.block_id
                          WHERE f.farm_id = b.farm_id
                            AND f.product_id = s.product_id
                            AND f.is_active
                            AND f.fetch_farm_aoi
                            AND f.deleted_at IS NULL
                      )
                    ORDER BY s.created_at ASC
                    """  # noqa: S608 - the predicate is a module literal, values are bound
                    ).bindparams(
                        bindparam("anchor_hour", type_=Integer()),
                        now=now,
                        default_cadence=default_cadence_hours,
                        anchor_hour=anchor_hour_utc,
                    )
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
        index_code: str,
        product_codes: Sequence[str],
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

        Counts BOTH acquisition paths, for the reason #462 taught the
        observer: a farm fetching its own AOI writes no per-block job at all,
        so reading only `imagery_ingestion_jobs` left a cut-over farm with an
        almost empty strip while its indices kept landing. That is the worst
        shape this bug can take — the strip is what SELECTS a pass, so no
        date offered means no pixels drawn, on a farm whose rasters and
        aggregates are all present and correct.

        The two tables do not share a status vocabulary: a block job skips as
        `skipped_cloud`, a farm job simply as `skipped` (cloud is the only
        reason the farm path skips one). Both fold into `skipped_cloud_count`
        so the strip can still say "cloudy" rather than greying the day out
        as unprocessed and losing the why.

        A farm job is ONE row covering every block, where the block path
        wrote one row per block. The per-block counts a farm pass reports are
        therefore the blocks its surface was measured against — the same
        live-block predicate `block_masks_for_farm` cuts the zonal step with,
        so the number under a date keeps meaning "blocks in this pass" across
        the cutover instead of dropping to 1.

        A day carrying both paths (the cutover day itself) takes the LARGER
        of the two rather than their sum, which no farm can exceed its own
        block count by.

        SQL lives in `_FARM_SCENE_DAYS_SQL` so its plan can be asserted on.
        Both branches read `block_index_aggregates` set-based, never once per
        day: a correlated per-day read of that hypertable measured 32 s on
        prod where the grouped one measures 380 ms, for identical rows.

        Scoped to ONE index, and through it to the products that can produce
        it. A farm subscribed to both `s2_l2a` and `landsat_c2_l2_st` has two
        independent acquisition streams on different cadences — 5 days and 1
        day on the reference farm — and merging them into one strip offers a
        date whose pass carries no raster for the index being drawn. Worse,
        the drawability test below is the SAME index the caller will render,
        so an unscoped strip marks a thermal pass undrawable (it has no
        `ndvi` aggregate, and never will) while marking a Sentinel-2 pass
        drawable for `lst` (which it cannot draw). Both errors point the
        console at a blank map, and the second one looks like a data gap
        rather than a bug.

        The index scoping does NOT reintroduce the correlated read: it adds
        an equality on `a.index_code` inside branches that were already
        grouped, which narrows the same single pass over the hypertable.
        """
        if not product_codes:
            # No product produces this index, so no pass can draw it. An
            # empty strip is the honest answer; an unfiltered query here
            # would offer every date the farm has ever seen.
            return ()
        rows = (
            (
                await self._session.execute(
                    text(_FARM_SCENE_DAYS_SQL).bindparams(
                        bindparam("farm", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_codes", expanding=True),
                    ),
                    {
                        "farm": farm_id,
                        "limit": limit,
                        "index_code": index_code,
                        "product_codes": list(product_codes),
                    },
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
        product_codes: Sequence[str],
    ) -> tuple[dict[str, Any], ...]:
        """One row per block: the index asset to render for a given pass.

        The console paints index PIXELS, and a pixel layer needs the COG's
        object key — which is derivable from ``stac_item_id``
        (``provider/product/scene/aoi``) and nothing else. Without this route
        the frontend would have to ask ``/blocks/{id}/scenes`` per block to
        find it: the same 36-request fan-out that ``/farms/{id}/scenes`` and
        ``/farms/{id}/grid-cells`` both exist to avoid.

        ``at`` is the timeline's scene bound, so each block resolves to ITS
        OWN latest pass at or before that instant. Blocks in different tiles
        are sensed minutes apart for what a grower calls one pass, and pinning
        every block to a single timestamp would drop whichever block was
        sensed a minute later.

        That tolerance is bounded to the acquisition DAY, and the bound is the
        whole point. Unbounded, "latest at or before" answers a question the
        caller did not ask: on a farm that has been cut over to farm-AOI
        fetching, the block table stops gaining rows, so every pass after the
        cutover resolved to the LAST PRE-CUTOVER PASS — 36 rows dated five
        days before the date on the timeline. The console then drew those
        stale rasters under today's label and left every acre outside a block
        grey, on a farm whose own surface for that exact pass was sitting in
        the same response. Minutes are one pass; days are not.

        Only ``succeeded`` jobs are eligible, and that is the whole guard:
        ``mark_succeeded`` is what sets ``stac_item_id`` in the first place,
        so a job in any other state either has no key or has one pointing at
        assets that were never written. A cloud-skipped pass in particular
        still leaves a job row — it belongs on the timeline, but pointing the
        tile server at it would 404 every tile and paint an empty block.

        ``resolution_m`` rides along because the legend turns a pixel COUNT
        into an AREA, and fetching the product's resolution separately would
        be one more request for a number this row already knows.

        ``product_codes`` scopes the answer to the products that can produce
        the index being drawn. The caller turns a row into a tile URL by
        appending ``<index>.tif`` to the key it derives from
        ``stac_item_id``, so handing back the newest job REGARDLESS of
        product hands back a key with no such object behind it — every tile
        404s and the block goes blank. That is not hypothetical on a farm
        carrying both products: thermal fetches daily against Sentinel-2's
        five, so the unscoped ``DISTINCT ON ... ORDER BY scene_datetime
        DESC`` lands on a Landsat job most days of the week.
        """
        clauses = [
            "b.farm_id = :farm",
            "j.stac_item_id IS NOT NULL",
            "j.status = 'succeeded'",
            "p.code IN :product_codes",
        ]
        if not product_codes:
            # Nothing produces this index, so no row can draw it.
            return ()
        params: dict[str, Any] = {"farm": farm_id, "product_codes": list(product_codes)}
        if at is not None:
            clauses.append("j.scene_datetime <= :at")
            clauses.append("j.scene_datetime >= :day_start")
            params["at"] = at
            params["day_start"] = _utc_day_start(at)
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
                        -- public, and INNER since the product scopes the row
                        -- to the index being drawn. It used to be LEFT, so a
                        -- product row we could not read cost the caller a
                        -- resolution rather than the block's imagery. That
                        -- trade no longer holds: without the product code we
                        -- cannot tell whether this pass carries the index at
                        -- all, and drawing the wrong product's raster is a
                        -- worse outcome than drawing none.
                        JOIN public.imagery_products p ON p.id = j.product_id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY j.block_id, j.scene_datetime DESC
                        """
                    ).bindparams(
                        bindparam("farm", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_codes", expanding=True),
                    ),
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
        blocks_merged: int | None,
        indices: list[str],
        source: str = "stitched",
    ) -> None:
        """Note that a farm-wide raster now exists for this pass.

        Upsert on (farm, pass, boundary): rebuilding a pass replaces the row
        rather than accumulating history nobody reads. The row is what lets the
        API answer "is there a farm raster here?" without probing the bucket,
        and what makes the cutover per farm — a farm with rows serves one
        raster, a farm without keeps the per-block path untouched.

        ``source`` says how the surface came to exist: ``stitched`` from block
        rasters, or ``fetched`` for the farm boundary. A fetched surface merged
        no blocks, so ``blocks_merged`` is None there rather than 0 — the count
        does not apply rather than being zero.

        A fetched surface WINS over a stitched one for the same pass: it covers
        ground no block was ever fetched for, so replacing it with a stitch
        would silently shrink the farm back to its blocks.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO farm_scene_rasters (
                    farm_id, product_id, scene_datetime, scene_id,
                    stac_item_id, aoi_hash, blocks_merged, indices, source
                )
                VALUES (
                    :farm, :product, :at, :scene_id,
                    :stac, :aoi_hash, :blocks, CAST(:indices AS jsonb), :source
                )
                ON CONFLICT (farm_id, scene_datetime, aoi_hash) DO UPDATE
                SET stac_item_id  = EXCLUDED.stac_item_id,
                    product_id    = EXCLUDED.product_id,
                    scene_id      = EXCLUDED.scene_id,
                    blocks_merged = EXCLUDED.blocks_merged,
                    indices       = EXCLUDED.indices,
                    source        = EXCLUDED.source,
                    built_at      = now()
                WHERE farm_scene_rasters.source <> 'fetched'
                   OR EXCLUDED.source = 'fetched'
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
                "source": source,
            },
        )

    async def get_farm_scene_raster(
        self,
        *,
        farm_id: UUID,
        at: datetime | None,
        product_codes: Sequence[str],
    ) -> dict[str, Any] | None:
        """The farm-wide raster to draw for a pass, or None if there is none.

        Matched against the farm's CURRENT aoi_hash: a farm reshaped since the
        raster was stitched falls back to the per-block path rather than
        drawing a surface cut to a boundary that no longer exists.

        Bounded to the acquisition day of ``at`` for the same reason the block
        assets are: asking for a 2024 pass and being handed the LATEST surface
        paints today's pixels under a timeline reading two years ago — a wrong
        answer wearing the shape of a right one. A pass with no surface of its
        own now returns None and falls back to the per-block path, which is
        merely seamed rather than untrue.

        And scoped to the products that can produce the index being drawn.
        There is one surface per (farm, pass, boundary) but no uniqueness
        across PRODUCTS, so a farm fetching both Sentinel-2 and Landsat holds
        two independent series of rows here. Ordering by ``scene_datetime``
        alone therefore answered "the newest surface of any product", and the
        caller appended ``<index>.tif`` to whatever came back — asking a
        Landsat surface for `ndvi` on every day the daily thermal pass
        out-ran the five-day optical one.
        """
        if not product_codes:
            return None
        clauses = ["r.farm_id = :farm", "r.aoi_hash = f.aoi_hash", "p.code IN :product_codes"]
        params: dict[str, Any] = {"farm": farm_id, "product_codes": list(product_codes)}
        if at is not None:
            clauses.append("r.scene_datetime <= :at")
            clauses.append("r.scene_datetime >= :day_start")
            params["at"] = at
            params["day_start"] = _utc_day_start(at)
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT r.scene_datetime, r.stac_item_id, r.product_id,
                               r.blocks_merged, r.source, p.resolution_m
                        FROM farm_scene_rasters r
                        JOIN farms f ON f.id = r.farm_id
                        -- INNER, not LEFT: the product code is what tells us
                        -- whether this surface carries the index at all.
                        JOIN public.imagery_products p ON p.id = r.product_id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY r.scene_datetime DESC
                        LIMIT 1
                        """
                    ).bindparams(
                        bindparam("farm", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_codes", expanding=True),
                    ),
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

    async def list_farm_block_boundaries(self, farm_id: UUID) -> tuple[dict[str, Any], ...]:
        """Every active block of a farm, with its UTM boundary.

        Feeds the zonal step: a block aggregate over the farm surface is that
        surface masked to this polygon. Same geometry the per-block pipeline
        cuts its own raster with, so the two paths are measuring the same
        ground and any difference in the numbers is real rather than
        definitional.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            b.id AS block_id,
                            ST_AsGeoJSON(b.boundary_utm)::text AS boundary_utm_geojson
                        FROM blocks b
                        WHERE b.farm_id = :farm
                          AND b.deleted_at IS NULL
                          AND (b.active_to IS NULL OR b.active_to > now())
                        ORDER BY b.id
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_block_index_means(
        self,
        *,
        farm_id: UUID,
        scene_datetime: datetime,
    ) -> dict[tuple[str, str], float]:
        """Stored per-block means for one pass, keyed by (block_id, index).

        The baseline the farm-raster aggregates are diffed against. These rows
        were written by the per-block pipeline; if the farm surface is measuring
        the same ground the numbers must land on top of each other.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT a.block_id::text, a.index_code, a.mean
                    FROM block_index_aggregates a
                    JOIN blocks b ON b.id = a.block_id
                    WHERE b.farm_id = :farm AND a.time = :at AND a.mean IS NOT NULL
                    """
                ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                {"farm": farm_id, "at": scene_datetime},
            )
        ).all()
        return {(r[0], r[1]): float(r[2]) for r in rows}

    # ---- Farm-AOI ingestion ----------------------------------------------
    #
    # Deliberately a parallel set rather than a widening of the block methods.
    # The block path carries every farm's daily imagery; a farm-AOI fetch is
    # switched on one farm at a time and must not be able to break it.

    async def get_farm_boundary(self, farm_id: UUID) -> dict[str, Any] | None:
        """Read `boundary`, `boundary_utm`, `aoi_hash`, `utm_srid` for a farm.

        The farm mirror of `get_block_boundary`, and the reason a farm-AOI
        fetch can cover ground that no block was ever drawn around.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT
                        f.aoi_hash,
                        f.utm_srid,
                        ST_AsGeoJSON(f.boundary)::text AS boundary_geojson,
                        ST_AsGeoJSON(f.boundary_utm)::text AS boundary_utm_geojson
                    FROM farms f
                    WHERE f.id = :id AND f.deleted_at IS NULL
                    """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": farm_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["boundary_geojson"] is None:
            return None
        return {
            "farm_id": farm_id,
            "aoi_hash": row["aoi_hash"],
            "boundary_geojson": json.loads(row["boundary_geojson"]),
            "boundary_utm_geojson": json.loads(row["boundary_utm_geojson"]),
            "utm_srid": int(row["utm_srid"]),
        }

    async def product_resolutions(self) -> dict[UUID, Any]:
        """`{product_id: resolution_m}` over every product, active or not.

        Not filtered to active products: a subscription can outlive the
        product's retirement, and answering "unknown resolution" for one would
        report a farm as fetchable when nothing has measured it.
        """
        rows = (
            await self._session.execute(
                text("SELECT id, resolution_m FROM public.imagery_products")
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    async def list_farm_subscriptions(
        self,
        *,
        farm_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["farm_id = :farm", "deleted_at IS NULL"]
        if not include_inactive:
            clauses.append("is_active = TRUE")
        rows = (
            (
                await self._session.execute(
                    text(
                        f"SELECT * FROM imagery_farm_subscriptions "  # noqa: S608
                        f"WHERE {' AND '.join(clauses)} ORDER BY created_at ASC"
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def count_active_block_subscriptions(self, *, farm_id: UUID, product_id: UUID) -> int:
        """Live blocks of this farm actually subscribed to this product.

        "The farm is subscribed, per block" is only true if some block is. A
        farm row on its own fetches nothing unless `fetch_farm_aoi` is set —
        the block sweep is driven by these rows and by nothing else.
        """
        row = await self._session.execute(
            text(
                """
                SELECT count(*) FROM imagery_aoi_subscriptions s
                  JOIN blocks b ON b.id = s.block_id
                 WHERE b.farm_id = :farm
                   AND b.deleted_at IS NULL
                   AND s.product_id = :product
                   AND s.is_active = TRUE
                   AND s.deleted_at IS NULL
                """
            ).bindparams(
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("product", type_=PG_UUID(as_uuid=True)),
            ),
            {"farm": farm_id, "product": product_id},
        )
        return int(row.scalar_one())

    async def has_block_imagery_history(self, *, farm_id: UUID, product_id: UUID) -> bool:
        """Has this farm ever been fetched per block for this product?

        The question behind it is whether moving the farm onto the whole-farm
        path would put a STEP in a series somebody is already reading. Block
        means measured off a stitched farm surface differ from the same block
        fetched on its own by around 0.7% — nothing on a farm with no history,
        a visible discontinuity on one with months of it.
        """
        row = await self._session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM imagery_ingestion_jobs j
                      JOIN blocks b ON b.id = j.block_id
                     WHERE b.farm_id = :farm
                       AND j.product_id = :product
                )
                """
            ).bindparams(
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("product", type_=PG_UUID(as_uuid=True)),
            ),
            {"farm": farm_id, "product": product_id},
        )
        return bool(row.scalar_one())

    async def subscribe_farm_blocks(
        self,
        *,
        farm_id: UUID,
        product_id: UUID,
        cadence_hours: int | None,
        cloud_cover_max_pct: int | None,
        actor_user_id: UUID | None,
    ) -> int:
        """Give every live block of the farm an active subscription.

        Used when the farm's own row says "per block" but no block carries the
        subscription that phrase describes. Blocks that already have one are
        left exactly as they are — including their watermarks, so this cannot
        re-fetch history.

        Ids are generated here rather than in SQL: `uuid7` is the platform's
        ordering guarantee and a `gen_random_uuid()` would break it.
        """
        block_ids = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT b.id FROM blocks b
                         WHERE b.farm_id = :farm
                           AND b.deleted_at IS NULL
                           AND (b.active_to IS NULL OR b.active_to > now())
                           AND NOT EXISTS (
                               SELECT 1 FROM imagery_aoi_subscriptions s
                                WHERE s.block_id = b.id
                                  AND s.product_id = :product
                                  AND s.is_active = TRUE
                                  AND s.deleted_at IS NULL
                           )
                        ORDER BY b.id
                        """
                    ).bindparams(
                        bindparam("farm", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"farm": farm_id, "product": product_id},
                )
            )
            .scalars()
            .all()
        )
        for block_id in block_ids:
            self._session.add(
                ImageryAoiSubscription(
                    id=uuid7(),
                    block_id=block_id,
                    product_id=product_id,
                    cadence_hours=cadence_hours,
                    cloud_cover_max_pct=cloud_cover_max_pct,
                    is_active=True,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
            )
        if block_ids:
            await self._session.flush()
        return len(block_ids)

    async def upsert_farm_subscription(
        self,
        *,
        subscription_id: UUID,
        farm_id: UUID,
        product_id: UUID,
        cadence_hours: int | None,
        cloud_cover_max_pct: int | None,
        fetch_farm_aoi: bool,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Create the farm's subscription to a product, or revive it.

        Revives rather than inserts a second row, because the unique index is
        PARTIAL — it covers only live rows, so a revoked subscription
        conflicts with nothing and a plain insert would leave the farm with
        two histories for one product.

        Reviving keeps the existing watermark, which is what stops
        re-subscribing from re-fetching everything back to the discovery
        floor.
        """
        existing = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT id FROM imagery_farm_subscriptions
                        WHERE farm_id = :farm AND product_id = :product
                          AND deleted_at IS NULL
                        ORDER BY is_active DESC, created_at DESC
                        LIMIT 1
                        """
                    ).bindparams(
                        bindparam("farm", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"farm": farm_id, "product": product_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            await self._session.execute(
                text(
                    """
                    UPDATE imagery_farm_subscriptions
                       SET cadence_hours = :cadence,
                           cloud_cover_max_pct = :cloud,
                           fetch_farm_aoi = :fetch,
                           is_active = TRUE,
                           updated_by = :actor,
                           updated_at = now()
                     WHERE id = :id
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": existing["id"],
                    "cadence": cadence_hours,
                    "cloud": cloud_cover_max_pct,
                    "fetch": fetch_farm_aoi,
                    "actor": actor_user_id,
                },
            )
            revived = await self.get_farm_subscription(existing["id"])
            assert revived is not None
            return revived

        await self._session.execute(
            text(
                """
                INSERT INTO imagery_farm_subscriptions (
                    id, farm_id, product_id, cadence_hours, cloud_cover_max_pct,
                    fetch_farm_aoi, is_active, created_by, updated_by
                )
                VALUES (
                    :id, :farm, :product, :cadence, :cloud,
                    :fetch, TRUE, :actor, :actor
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("product", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": subscription_id,
                "farm": farm_id,
                "product": product_id,
                "cadence": cadence_hours,
                "cloud": cloud_cover_max_pct,
                "fetch": fetch_farm_aoi,
                "actor": actor_user_id,
            },
        )
        created = await self.get_farm_subscription(subscription_id)
        assert created is not None
        return created

    async def update_farm_subscription(
        self,
        *,
        subscription_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        """Apply only the fields the caller named."""
        if not changes:
            return await self.get_farm_subscription(subscription_id)
        sets = [f"{col} = :{col}" for col in changes]
        sets += ["updated_by = :actor", "updated_at = now()"]
        params: dict[str, Any] = {**changes, "id": subscription_id, "actor": actor_user_id}
        await self._session.execute(
            text(
                f"UPDATE imagery_farm_subscriptions SET {', '.join(sets)} "  # noqa: S608
                "WHERE id = :id AND deleted_at IS NULL"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )
        return await self.get_farm_subscription(subscription_id)

    async def get_farm_subscription(self, subscription_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT * FROM imagery_farm_subscriptions
                    WHERE id = :id AND deleted_at IS NULL
                    """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": subscription_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def list_farm_subscriptions_due(
        self,
        *,
        default_cadence_hours: int,
        now: datetime,
        anchor_hour_utc: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Active farm subscriptions with the farm-AOI fetch switched ON.

        `fetch_farm_aoi` is the gate, and it is why deploying this does
        nothing: 0074 created an active farm subscription for every farm that
        had block subscriptions, so without the flag every farm on the
        platform would start fetching a second, larger AOI on the next beat.

        ``anchor_hour_utc`` adds the daily anchor rule — see
        `_due_predicate_sql`.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                    SELECT * FROM imagery_farm_subscriptions
                    WHERE is_active = TRUE
                      AND fetch_farm_aoi = TRUE
                      AND deleted_at IS NULL
                      AND {_due_predicate_sql()}
                    ORDER BY created_at ASC
                    """  # noqa: S608 - the predicate is a module literal, values are bound
                    ).bindparams(
                        bindparam("anchor_hour", type_=Integer()),
                        now=now,
                        default_cadence=default_cadence_hours,
                        anchor_hour=anchor_hour_utc,
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def disable_farm_aoi_fetch(self, *, subscription_id: UUID) -> None:
        """Switch one farm back to the block path.

        Called when the provider could not return this farm in one request.
        It is a fallback, not a preference: `fetch_farm_aoi` is also what
        excludes the farm's blocks from the block sweep, so a farm left ON
        while unfetchable is a farm receiving no imagery at all.
        """
        await self._session.execute(
            text(
                "UPDATE imagery_farm_subscriptions "
                "SET fetch_farm_aoi = FALSE, updated_at = now() WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": subscription_id},
        )

    async def list_farm_subscriptions_fetching_aoi(
        self, farm_id: UUID, *, product_codes: Sequence[str] | None = None
    ) -> tuple[UUID, ...]:
        """Farm subscriptions on one farm with the farm-AOI fetch switched ON.

        The backfill dispatcher's half of the cutover gate. Same predicate as
        `list_farm_subscriptions_due` minus the cadence clause: a backfill is
        operator-driven and takes an explicit window, so "is it due?" does not
        apply.

        ``product_codes`` narrows to specific products. The backfill console
        offers optical and thermal as separate sources — they have different
        cadence, cost and failure modes — so a run for one must not quietly
        fetch the other and report it under the wrong counter. None means
        every product, which is what the live sweep wants.
        """
        clauses = [
            "farm_id = :farm",
            "is_active = TRUE",
            "fetch_farm_aoi = TRUE",
            "deleted_at IS NULL",
        ]
        params: dict[str, Any] = {"farm": farm_id}
        binds: list[Any] = [bindparam("farm", type_=PG_UUID(as_uuid=True))]
        if product_codes is not None:
            clauses.append(
                "product_id IN (SELECT id FROM public.imagery_products" " WHERE code = ANY(:codes))"
            )
            params["codes"] = list(product_codes)
            binds.append(bindparam("codes", type_=ARRAY(Text())))
        rows = (
            await self._session.execute(
                text(
                    f"""
                    SELECT id FROM imagery_farm_subscriptions
                    WHERE {" AND ".join(clauses)}
                    ORDER BY created_at ASC
                    """  # noqa: S608 - clauses are literals, values are bound
                ).bindparams(*binds),
                params,
            )
        ).all()
        return tuple(r[0] for r in rows)

    async def list_block_subscriptions_for_backfill(
        self, farm_id: UUID, *, product_codes: Sequence[str] | None = None
    ) -> tuple[UUID, ...]:
        """Block subscriptions on one farm that a backfill should still fetch.

        Mirrors the live sweep's exclusion in `list_active_subscriptions_due`
        exactly, and for the same reason: on a cut-over farm one whole-farm
        fetch already covers this block, so fetching it separately pays the
        provider twice for the same ground — and lands the result in the block
        tables, giving that farm a history shaped unlike its live data.

        The exclusion is keyed on `fetch_farm_aoi`, never on a farm
        subscription merely existing: 0074 created one for every farm that had
        block subscriptions, so the existence predicate would silently turn
        every backfill on the platform into a no-op.
        """
        clauses = [
            "b.farm_id = :farm",
            "s.is_active = TRUE",
            "s.deleted_at IS NULL",
            """NOT EXISTS (
                          SELECT 1
                          FROM imagery_farm_subscriptions f
                          WHERE f.farm_id = b.farm_id
                            AND f.product_id = s.product_id
                            AND f.is_active
                            AND f.fetch_farm_aoi
                            AND f.deleted_at IS NULL
                      )""",
        ]
        params: dict[str, Any] = {"farm": farm_id}
        binds: list[Any] = [bindparam("farm", type_=PG_UUID(as_uuid=True))]
        if product_codes is not None:
            clauses.append(
                "s.product_id IN (SELECT id FROM public.imagery_products"
                " WHERE code = ANY(:codes))"
            )
            params["codes"] = list(product_codes)
            binds.append(bindparam("codes", type_=ARRAY(Text())))
        rows = (
            await self._session.execute(
                text(
                    f"""
                    SELECT s.id FROM imagery_aoi_subscriptions s
                    JOIN blocks b ON b.id = s.block_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY s.created_at ASC
                    """  # noqa: S608 - clauses are literals, values are bound
                ).bindparams(*binds),
                params,
            )
        ).all()
        return tuple(r[0] for r in rows)

    async def touch_farm_subscription_attempt(
        self,
        *,
        subscription_id: UUID,
        attempted_at: datetime,
        ingested: bool,
    ) -> None:
        """Record the poll; advance the ingest watermark only if it found work.

        Same contract as the block path: an empty or all-cloud poll is a
        heartbeat, not an ingest, and bumping the watermark on one would bury
        publication-lagged scenes.
        """
        sets = ["last_attempted_at = :at", "updated_at = now()"]
        if ingested:
            sets.append("last_successful_ingest_at = :at")
        await self._session.execute(
            text(
                f"UPDATE imagery_farm_subscriptions SET {', '.join(sets)} "  # noqa: S608
                "WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": subscription_id, "at": attempted_at},
        )

    async def upsert_pending_farm_job(
        self,
        *,
        job_id: UUID,
        subscription_id: UUID,
        farm_id: UUID,
        product_id: UUID,
        scene_id: str,
        scene_datetime: datetime,
        cloud_cover_pct: Decimal | None,
    ) -> tuple[UUID, bool]:
        """Insert a `pending` farm job; return (job_id, created).

        Same idempotency key as the block table — UNIQUE(subscription, scene) —
        so re-discovery of a scene already seen returns created=False.
        """
        result = await self._session.execute(
            text(
                """
                INSERT INTO imagery_farm_ingestion_jobs (
                    id, subscription_id, farm_id, product_id, scene_id,
                    scene_datetime, cloud_cover_pct, status, requested_at
                )
                VALUES (
                    :id, :subscription_id, :farm_id, :product_id, :scene_id,
                    :scene_datetime, :cloud_cover_pct, 'pending', now()
                )
                ON CONFLICT (subscription_id, scene_id) DO NOTHING
                RETURNING id
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("subscription_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                bindparam("product_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": job_id,
                "subscription_id": subscription_id,
                "farm_id": farm_id,
                "product_id": product_id,
                "scene_id": scene_id,
                "scene_datetime": scene_datetime,
                "cloud_cover_pct": cloud_cover_pct,
            },
        )
        inserted = result.scalar()
        if inserted is not None:
            return UUID(str(inserted)), True
        existing = (
            await self._session.execute(
                text(
                    "SELECT id FROM imagery_farm_ingestion_jobs "
                    "WHERE subscription_id = :s AND scene_id = :scene"
                ).bindparams(bindparam("s", type_=PG_UUID(as_uuid=True))),
                {"s": subscription_id, "scene": scene_id},
            )
        ).scalar_one()
        return UUID(str(existing)), False

    async def get_farm_job(self, job_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM imagery_farm_ingestion_jobs WHERE id = :id").bindparams(
                        bindparam("id", type_=PG_UUID(as_uuid=True))
                    ),
                    {"id": job_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def list_pending_farm_jobs(self, *, subscription_id: UUID) -> tuple[UUID, ...]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT id FROM imagery_farm_ingestion_jobs "
                    "WHERE subscription_id = :s AND status = 'pending'"
                ).bindparams(bindparam("s", type_=PG_UUID(as_uuid=True))),
                {"s": subscription_id},
            )
        ).all()
        return tuple(UUID(str(r[0])) for r in rows)

    async def set_farm_job_status(
        self,
        *,
        job_id: UUID,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        error_code: str | None = None,
        stac_item_id: str | None = None,
        assets_written: list[str] | None = None,
    ) -> None:
        """One setter for every terminal and non-terminal transition.

        The block path grew a method per status; there is no reason to repeat
        that shape here, and one setter keeps the states visible in one place.
        """
        sets = ["status = :status"]
        params: dict[str, Any] = {"id": job_id, "status": status}
        for column, value in (
            ("started_at", started_at),
            ("completed_at", completed_at),
            ("error_message", error_message),
            ("error_code", error_code),
            ("stac_item_id", stac_item_id),
        ):
            if value is not None:
                sets.append(f"{column} = :{column}")
                params[column] = value
        if assets_written is not None:
            sets.append("assets_written = CAST(:assets AS jsonb)")
            params["assets"] = json.dumps(assets_written)
        await self._session.execute(
            text(
                f"UPDATE imagery_farm_ingestion_jobs SET {', '.join(sets)} "  # noqa: S608
                "WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            params,
        )
        await self._session.flush()

    async def get_block_boundary(self, block_id: UUID) -> dict[str, Any] | None:
        """Read `boundary`, `boundary_utm`, `aoi_hash`, `farm_id`, `utm_srid`.

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
                        ST_SRID(b.boundary_utm) AS utm_srid,
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
            "utm_srid": int(row["utm_srid"]),
        }

    # ---- Stuck-job recovery ------------------------------------------------
    #
    # A job whose worker dies between `mark_running` and the terminal write
    # stays non-terminal for ever. Nothing else recovers it: re-discovery
    # cannot re-create the row (ON CONFLICT DO NOTHING on
    # (subscription_id, scene_id)), the re-dispatch query reads only
    # `status = 'pending'`, and `acquire_scene` no-ops on any job that is not
    # `pending`. So the row must be moved back to `pending` by hand, which is
    # what these two methods do.
    #
    # Both take the same shape, because both job tables have the same
    # problem. The farm table is not a copy for its own sake: thermal has no
    # block-path rows at all, so a block-only reaper would leave every
    # thermal job unprotected.

    async def fail_exhausted_stuck_jobs(
        self,
        *,
        stuck_hours: int,
        max_attempts: int,
        farm_path: bool,
    ) -> int:
        """Mark stuck jobs that have used up their resets as failed.

        Without this a job that can never succeed is reset on every sweep for
        ever. `error_code` is `stuck_no_progress` so the failure-streak
        detector can see it; a job silently parked in `pending` would be
        invisible to every detector we have.
        """
        table = "imagery_farm_ingestion_jobs" if farm_path else "imagery_ingestion_jobs"
        result = await self._session.execute(
            text(
                f"""
                UPDATE {table}
                   SET status = 'failed',
                       completed_at = now(),
                       error_message =
                           'reaped after ' || attempts ||
                           ' attempt(s) with no terminal status',
                       error_code = 'stuck_no_progress'
                 WHERE status IN ('pending', 'running', 'requested')
                   AND requested_at < now() - make_interval(hours => :stuck_hours)
                   AND attempts >= :max_attempts
                """  # noqa: S608 - `table` is one of two literals
            ),
            {"stuck_hours": stuck_hours, "max_attempts": max_attempts},
        )
        # Same shape as `reset_ingest_watermarks` earlier in this file:
        # SQLAlchemy 2.x only defines `rowcount` on a DML result.
        return int(getattr(result, "rowcount", 0) or 0)

    async def reset_stuck_jobs(
        self,
        *,
        stuck_hours: int,
        max_attempts: int,
        farm_path: bool,
    ) -> tuple[UUID, ...]:
        """Return stuck jobs to `pending` and return their ids to re-dispatch.

        `started_at` and the previous error are cleared so the retried run
        reads like a first run rather than carrying a half-finished one's
        state. `attempts` is incremented in the same statement, so a crash
        between the reset and the dispatch still costs the job one attempt
        and cannot loop.

        Call `fail_exhausted_stuck_jobs` first. The two predicates are
        disjoint on `attempts`, so the order only decides whether a job that
        crosses the limit this sweep is failed now or on the next one.
        """
        table = "imagery_farm_ingestion_jobs" if farm_path else "imagery_ingestion_jobs"
        rows = (
            await self._session.execute(
                text(
                    f"""
                    UPDATE {table}
                       SET status = 'pending',
                           attempts = attempts + 1,
                           started_at = NULL,
                           completed_at = NULL,
                           error_message = NULL,
                           error_code = NULL
                     WHERE status IN ('pending', 'running', 'requested')
                       AND requested_at < now() - make_interval(hours => :stuck_hours)
                       AND attempts < :max_attempts
                    RETURNING id
                    """  # noqa: S608 - `table` is one of two literals
                ),
                {"stuck_hours": stuck_hours, "max_attempts": max_attempts},
            )
        ).all()
        return tuple(UUID(str(r[0])) for r in rows)


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
