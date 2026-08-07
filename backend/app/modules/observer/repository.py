"""Read-only SQL for the Observer console.

Raw SQL over an admin session that is scoped to one tenant schema per call.
No ORM models: Observer reads other modules' tables and must not acquire a
mapper-level dependency on them — a column rename in imagery should surface
here as a failing Observer test, not as an import cycle.

Two conventions run through every query in this file.

**Time bounds are interpolated, never bound.** `block_index_aggregates` and
`block_grid_aggregates` are TimescaleDB hypertables. A bound parameter in the
time predicate gives the planner nothing to exclude chunks with, so it scans
every chunk in the table — the Farm Console's 7-second load was exactly this.
Interpolating a literal restores plan-time chunk exclusion. The interpolated
value is always a `datetime` this module formats itself (see `_ts`), never a
caller string, so the S608 injection heuristic is a false positive.

**Block scope is resolved once, then reused.** Callers pass a farm and an
optional block subset; `resolve_block_ids` turns that into a concrete list and
every downstream query filters on it. An empty list means the farm has no
matching blocks, and every count is legitimately zero — the queries are not
run at all rather than being handed an empty `IN ()`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# Job statuses, from the CHECK on `imagery_ingestion_jobs` (tenant 0003).
# Mirrored here because Observer groups by them; a new status added upstream
# without updating this constant would silently vanish from the histogram,
# so `test_job_status_constant_matches_check_constraint` pins the pair.
JOB_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped_cloud",
    "skipped_duplicate",
)

# Buckets the histogram supports. Closed set — interpolated into a
# `date_trunc` call, so it must never accept caller input directly.
BUCKETS: dict[str, str] = {"day": "day", "week": "week", "month": "month"}


def _ts(value: datetime) -> str:
    """Render a datetime as a SQL timestamptz literal.

    The one thing this file interpolates. Callers hand in `datetime` objects
    parsed by pydantic at the router boundary; the isinstance check makes that
    a hard guarantee rather than a convention, so no caller-controlled string
    can reach the query text.
    """
    if not isinstance(value, datetime):
        raise TypeError(f"time bound must be a datetime, got {type(value).__name__}")
    return f"TIMESTAMPTZ '{value.isoformat()}'"


class ObserverRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ---- scope ----------------------------------------------------------

    async def resolve_block_ids(
        self,
        *,
        farm_id: UUID,
        block_ids: list[UUID] | None,
    ) -> list[UUID]:
        """Blocks in scope: the farm's live blocks, optionally narrowed.

        A requested block that does not belong to the farm is dropped rather
        than erroring — the caller's selection is a filter, and silently
        widening scope across farms would be worse than ignoring a stale id.
        """
        sql = """
            SELECT b.id
              FROM blocks b
             WHERE b.farm_id = :fid
               AND b.deleted_at IS NULL
        """
        params: dict[str, Any] = {"fid": str(farm_id)}
        if block_ids:
            stmt = text(sql + " AND b.id IN :bids").bindparams(bindparam("bids", expanding=True))
            params["bids"] = [str(b) for b in block_ids]
        else:
            stmt = text(sql)
        rows = (await self._s.execute(stmt, params)).all()
        return [r[0] for r in rows]

    # ---- pickers --------------------------------------------------------

    async def list_farms(self) -> list[dict[str, Any]]:
        """Farms with the "is there anything to observe here" summary.

        Deliberately more than name + id: an operator picking a farm wants to
        know before they click whether it has subscriptions, whether any block
        is gridded, and what date range actually holds scenes. A farm with
        zero scenes looks identical to a broken pipeline until you can see
        that it was never subscribed.
        """
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT
                      f.id,
                      f.name,
                      f.code,
                      (SELECT count(*) FROM blocks b
                        WHERE b.farm_id = f.id AND b.deleted_at IS NULL) AS block_count,
                      (SELECT count(DISTINCT s.block_id)
                         FROM imagery_aoi_subscriptions s
                         JOIN blocks b ON b.id = s.block_id
                        WHERE b.farm_id = f.id
                          AND b.deleted_at IS NULL
                          AND s.is_active = TRUE
                          AND s.deleted_at IS NULL) AS blocks_with_imagery_sub,
                      (SELECT count(DISTINCT g.block_id)
                         FROM grid_configs g
                         JOIN blocks b ON b.id = g.block_id
                        WHERE b.farm_id = f.id
                          AND b.deleted_at IS NULL
                          AND g.retired_at IS NULL
                          AND g.deleted_at IS NULL) AS blocks_with_grid,
                      EXISTS (SELECT 1 FROM weather_subscriptions w
                               JOIN blocks b ON b.id = w.block_id
                              WHERE b.farm_id = f.id
                                AND w.is_active = TRUE
                                AND w.deleted_at IS NULL) AS has_weather_sub,
                      (SELECT min(j.scene_datetime) FROM imagery_ingestion_jobs j
                         JOIN blocks b ON b.id = j.block_id
                        WHERE b.farm_id = f.id) AS first_scene_at,
                      (SELECT max(j.scene_datetime) FROM imagery_ingestion_jobs j
                         JOIN blocks b ON b.id = j.block_id
                        WHERE b.farm_id = f.id) AS last_scene_at
                    FROM farms f
                   WHERE f.deleted_at IS NULL
                   ORDER BY f.name
                    """
                )
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def list_products_for_farm(self, farm_id: UUID) -> list[dict[str, Any]]:
        """Products this farm actually has jobs or subscriptions for.

        Offering the whole platform catalog would let an operator select a
        product with no data and read the resulting zeros as a fault.
        `provider_code` comes from a join — `imagery_products` does not carry
        one.
        """
        rows = (
            await self._s.execute(
                text(
                    """
                    WITH used AS (
                        SELECT DISTINCT j.product_id
                          FROM imagery_ingestion_jobs j
                          JOIN blocks b ON b.id = j.block_id
                         WHERE b.farm_id = :fid AND b.deleted_at IS NULL
                        UNION
                        SELECT DISTINCT s.product_id
                          FROM imagery_aoi_subscriptions s
                          JOIN blocks b ON b.id = s.block_id
                         WHERE b.farm_id = :fid
                           AND b.deleted_at IS NULL
                           AND s.deleted_at IS NULL
                    )
                    SELECT p.id, p.code, p.name, p.resolution_m,
                           p.bands, p.supported_indices,
                           pr.code AS provider_code, pr.name AS provider_name
                      FROM used u
                      JOIN public.imagery_products p ON p.id = u.product_id
                      JOIN public.imagery_providers pr ON pr.id = p.provider_id
                     ORDER BY pr.code, p.code
                    """
                ),
                {"fid": str(farm_id)},
            )
        ).mappings()
        return [dict(r) for r in rows]

    # ---- L0: stage counts ------------------------------------------------

    async def job_stage_counts(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, int]:
        """Counts for the first three ribbon stages, in one pass."""
        prod = "AND j.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT
              count(*) AS discovered,
              count(*) FILTER (
                WHERE j.status = 'succeeded' AND j.stac_item_id IS NOT NULL
              ) AS acquired,
              count(*) FILTER (WHERE j.status = 'failed') AS failed,
              count(*) FILTER (WHERE j.status IN ('pending', 'running')) AS in_flight,
              count(*) FILTER (
                WHERE j.status IN ('skipped_cloud', 'skipped_duplicate')
              ) AS skipped
              FROM imagery_ingestion_jobs j
             WHERE j.block_id IN :bids
               {prod}
               AND j.scene_datetime >= {_ts(window_from)}
               AND j.scene_datetime < {_ts(window_to)}
        """
        row = await self._one(sql, block_ids=block_ids, product_id=product_id)
        return {k: int(v) for k, v in row.items()}

    async def scenes_with_indices(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, int]:
        """Distinct scenes that produced block aggregates, and the row count.

        `scenes` is the ribbon's "indices computed" node; `rows` is the
        aggregate node beneath it. Both come from the same scan.
        """
        prod = "AND a.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT
              count(DISTINCT (a.time, a.block_id, a.product_id)) AS scenes,
              count(*) AS rows_written,
              count(DISTINCT a.index_code) AS index_codes
              FROM block_index_aggregates a
             WHERE a.block_id IN :bids
               {prod}
               AND a.time >= {_ts(window_from)}
               AND a.time < {_ts(window_to)}
        """
        row = await self._one(sql, block_ids=block_ids, product_id=product_id)
        return {
            "scenes": int(row["scenes"]),
            "rows": int(row["rows_written"]),
            "index_codes": int(row["index_codes"]),
        }

    async def cell_aggregate_coverage(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, int]:
        """Cell-aggregate counts *and the denominator that makes them mean something*.

        Reporting "402 of 1,215" here would be a lie dressed as a metric: a
        scene on a block with no grid is not a missing cell aggregate, it is a
        scene that was never supposed to have one. So `expected` counts only
        scenes whose block had a grid config **governing the scene's own
        time** — the valid-time predicate from tenant 0054, not "is there a
        grid today". Gridding a 2025 scene on a 2026 geometry is precisely the
        bug that migration exists to prevent, and an Observer that used the
        current geometry would report those scenes as healthy.
        """
        prod_a = "AND a.product_id = :pid" if product_id else ""
        prod_j = "AND j.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT
              (SELECT count(*) FROM (
                 SELECT DISTINCT a.time, a.block_id, a.product_id
                   FROM block_grid_aggregates a
                  WHERE a.block_id IN :bids
                    {prod_a}
                    AND a.time >= {_ts(window_from)}
                    AND a.time < {_ts(window_to)}
               ) g) AS produced,
              (SELECT count(*) FROM (
                 SELECT DISTINCT j.scene_datetime, j.block_id, j.product_id
                   FROM imagery_ingestion_jobs j
                  WHERE j.block_id IN :bids
                    {prod_j}
                    AND j.status = 'succeeded'
                    AND j.scene_datetime >= {_ts(window_from)}
                    AND j.scene_datetime < {_ts(window_to)}
                    AND EXISTS (
                          SELECT 1 FROM grid_configs cfg
                           WHERE cfg.block_id = j.block_id
                             AND cfg.product_id = j.product_id
                             AND cfg.deleted_at IS NULL
                             AND cfg.superseded_at IS NULL
                             AND tstzrange(cfg.effective_from, cfg.effective_to)
                                 @> j.scene_datetime
                    )
               ) e) AS expected
        """  # noqa: S608
        row = await self._one(sql, block_ids=block_ids, product_id=product_id)
        return {"produced": int(row["produced"]), "expected": int(row["expected"])}

    async def trend_coverage(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, Any]:
        """Continuous-aggregate coverage vs. the scene days that should be in it.

        `block_index_daily` is a *real-time* aggregate: above the
        materialization watermark it computes live, below it serves only what
        was materialized. Its refresh policy is a rolling 3-day window. So
        history written by a backfill is never materialized and never
        recomputed — it simply is not in the view, while the underlying
        aggregate rows are right there. That is #336, and querying the view is
        the only way to see it.

        Caveat this method reports rather than hides: the CAGG groups by
        (day, block, index) with **no product dimension**, so when a block has
        aggregates from more than one product the covered-day count cannot be
        attributed to one of them. `product_ambiguous` says when that is the
        case, so the UI can qualify the number instead of overstating it.
        """
        prod = "AND a.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT
              (SELECT count(*) FROM (
                 SELECT DISTINCT date_trunc('day', a.time) AS d, a.block_id
                   FROM block_index_aggregates a
                  WHERE a.block_id IN :bids
                    {prod}
                    AND a.time >= {_ts(window_from)}
                    AND a.time < {_ts(window_to)}
               ) s) AS scene_days,
              (SELECT count(*) FROM (
                 SELECT DISTINCT c.day, c.block_id
                   FROM block_index_daily c
                  WHERE c.block_id IN :bids
                    AND c.day >= {_ts(window_from)}
                    AND c.day < {_ts(window_to)}
               ) t) AS trend_days,
              (SELECT count(DISTINCT a2.product_id) FROM block_index_aggregates a2
                WHERE a2.block_id IN :bids
                  AND a2.time >= {_ts(window_from)}
                  AND a2.time < {_ts(window_to)}
              ) AS products_present
        """  # noqa: S608
        row = await self._one(sql, block_ids=block_ids, product_id=product_id)
        return {
            "scene_days": int(row["scene_days"]),
            "trend_days": int(row["trend_days"]),
            "product_ambiguous": int(row["products_present"]) > 1,
        }

    async def consumer_counts(
        self,
        *,
        block_ids: list[UUID],
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, int]:
        """Alerts and recommendations created on these blocks in the window.

        A proxy, and labelled as one in the API: this counts what was created
        in the window, not what provably descends from these scenes. True
        per-number lineage is OBS-8. The ribbon still wants the order of
        magnitude — "1,200 scenes in, zero recommendations out" is worth
        seeing before anyone has built the exact edge.
        """
        sql = f"""
            SELECT
              (SELECT count(*) FROM alerts al
                WHERE al.block_id IN :bids
                  AND al.deleted_at IS NULL
                  AND al.created_at >= {_ts(window_from)}
                  AND al.created_at < {_ts(window_to)}) AS alerts,
              (SELECT count(*) FROM recommendations r
                WHERE r.block_id IN :bids
                  AND r.deleted_at IS NULL
                  AND r.created_at >= {_ts(window_from)}
                  AND r.created_at < {_ts(window_to)}) AS recommendations
        """  # noqa: S608
        row = await self._one(sql, block_ids=block_ids, product_id=None)
        return {k: int(v) for k, v in row.items()}

    async def calc_versions_present(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> list[dict[str, Any]]:
        """Distinct calc versions over the window, most-used first.

        More than one version in a window means the trend line mixes
        methodologies — the pre-SCL-mask rows are the worked example, since
        they were averaged over cloud and so read high. Nothing else in the
        product can tell those rows apart from current ones.
        """
        prod = "AND r.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT r.calc_version,
                   r.mask_ruleset,
                   count(*) AS runs,
                   min(r.scene_time) AS first_scene_time,
                   max(r.scene_time) AS last_scene_time
              FROM indices_calc_runs r
             WHERE r.block_id IN :bids
               {prod}
               AND r.outcome = 'ok'
               AND r.scene_time >= {_ts(window_from)}
               AND r.scene_time < {_ts(window_to)}
             GROUP BY r.calc_version, r.mask_ruleset
             ORDER BY count(*) DESC
        """
        rows = await self._all(sql, block_ids=block_ids, product_id=product_id)
        return [dict(r) for r in rows]

    async def scene_calc_history(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        """Every recorded execution for one scene, newest first.

        This is what makes a silent overwrite visible. Aggregate rows are
        upserted on their composite key, so a recompute replaces the numbers
        with no trace; the run rows accumulate instead, and two of them with
        different `calc_version` values is the signature of exactly that.
        """
        sql = f"""
            SELECT r.id, r.job_id, r.calc_version, r.mask_ruleset,
                   r.trigger, r.outcome, r.error,
                   r.aoi_pixel_count, r.masked_pixel_count,
                   r.cell_count, r.grid_config_id, r.band_order,
                   r.per_index, r.started_at, r.completed_at, r.duration_ms,
                   r.created_at
              FROM indices_calc_runs r
             WHERE r.block_id = :bid
               AND r.product_id = :pid
               AND r.scene_time = {_ts(scene_time)}
             -- `id` breaks the tie: `created_at` defaults to now(), which is
             -- the *transaction* timestamp, so two runs recorded in one
             -- transaction share it exactly. uuid_generate_v7 is
             -- time-ordered, which makes this ordering total.
             ORDER BY r.created_at DESC, r.id DESC
        """
        rows = (
            await self._s.execute(text(sql), {"bid": str(block_id), "pid": str(product_id)})
        ).mappings()
        return [dict(r) for r in rows]

    # ---- L0: histogram ---------------------------------------------------

    async def scene_histogram(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        bucket: str,
    ) -> list[dict[str, Any]]:
        """Scene counts per time bucket, split by outcome.

        `computed` is not a job status — it is "the job succeeded *and*
        aggregates exist for it". A job that downloaded fine but whose index
        computation died reads as succeeded in `imagery_ingestion_jobs`, which
        is exactly the failure #335 hid. Splitting the two here is what makes
        the histogram show the gap.
        """
        trunc = BUCKETS[bucket]  # KeyError is a programmer error; router validates
        prod = "AND j.product_id = :pid" if product_id else ""
        sql = f"""
            SELECT
              date_trunc('{trunc}', j.scene_datetime) AS bucket,
              count(*) FILTER (
                WHERE j.status = 'succeeded' AND agg.present
              ) AS computed,
              count(*) FILTER (
                WHERE j.status = 'succeeded' AND NOT agg.present
              ) AS acquired_only,
              count(*) FILTER (
                WHERE j.status IN ('skipped_cloud', 'skipped_duplicate')
              ) AS skipped,
              count(*) FILTER (WHERE j.status = 'failed') AS failed,
              count(*) FILTER (WHERE j.status IN ('pending', 'running')) AS pending,
              count(*) AS total
              FROM imagery_ingestion_jobs j
              CROSS JOIN LATERAL (
                SELECT EXISTS (
                  SELECT 1 FROM block_index_aggregates a
                   WHERE a.block_id = j.block_id
                     AND a.product_id = j.product_id
                     AND a.time = j.scene_datetime
                     AND a.time >= {_ts(window_from)}
                     AND a.time < {_ts(window_to)}
                ) AS present
              ) agg
             WHERE j.block_id IN :bids
               {prod}
               AND j.scene_datetime >= {_ts(window_from)}
               AND j.scene_datetime < {_ts(window_to)}
             GROUP BY 1
             ORDER BY 1
        """  # noqa: S608
        rows = await self._all(sql, block_ids=block_ids, product_id=product_id)
        return [dict(r) for r in rows]

    # ---- L1: scene table -------------------------------------------------

    async def list_scenes(
        self,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        statuses: list[str] | None,
        max_valid_pct: float | None,
        with_error: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """One row per (scene, block), with what each stage produced.

        `indices_written` and `cells_written` are correlated subqueries rather
        than joins: a job with no aggregates must appear with a zero, and an
        inner join would drop exactly the rows an operator opens this table to
        find.
        """
        prod = "AND j.product_id = :pid" if product_id else ""
        filters = ""
        params: dict[str, Any] = {}
        if statuses:
            filters += " AND j.status IN :statuses"
            params["statuses"] = statuses
        if max_valid_pct is not None:
            filters += " AND j.valid_pixel_pct IS NOT NULL AND j.valid_pixel_pct < :maxvp"
            params["maxvp"] = max_valid_pct
        if with_error:
            filters += " AND (j.error_code IS NOT NULL OR j.error_message IS NOT NULL)"

        sql = f"""
            SELECT
              j.id AS job_id,
              j.block_id,
              b.name AS block_name,
              b.code AS block_code,
              j.product_id,
              j.scene_id,
              j.scene_datetime,
              j.status,
              j.cloud_cover_pct,
              j.valid_pixel_pct,
              j.error_code,
              j.error_message,
              j.stac_item_id,
              j.started_at,
              j.completed_at,
              EXTRACT(EPOCH FROM (j.completed_at - j.started_at)) AS duration_s,
              (SELECT count(*) FROM block_index_aggregates a
                WHERE a.block_id = j.block_id
                  AND a.product_id = j.product_id
                  AND a.time = j.scene_datetime) AS indices_written,
              (SELECT count(DISTINCT a.cell_id) FROM block_grid_aggregates a
                WHERE a.block_id = j.block_id
                  AND a.product_id = j.product_id
                  AND a.time = j.scene_datetime) AS cells_written,
              (SELECT count(*) FROM grid_cells gc
                 JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                WHERE cfg.block_id = j.block_id
                  AND cfg.product_id = j.product_id
                  AND cfg.deleted_at IS NULL
                  AND cfg.superseded_at IS NULL
                  AND tstzrange(cfg.effective_from, cfg.effective_to)
                      @> j.scene_datetime) AS cells_expected
              FROM imagery_ingestion_jobs j
              JOIN blocks b ON b.id = j.block_id
             WHERE j.block_id IN :bids
               {prod}
               {filters}
               AND j.scene_datetime >= {_ts(window_from)}
               AND j.scene_datetime < {_ts(window_to)}
             ORDER BY j.scene_datetime DESC, b.name
             LIMIT :limit OFFSET :offset
        """  # noqa: S608
        params.update({"limit": limit, "offset": offset})
        stmt = text(sql).bindparams(bindparam("bids", expanding=True))
        if statuses:
            stmt = stmt.bindparams(bindparam("statuses", expanding=True))
        params["bids"] = [str(b) for b in block_ids]
        if product_id:
            params["pid"] = str(product_id)
        rows = (await self._s.execute(stmt, params)).mappings()
        return [dict(r) for r in rows]

    async def scene_index_rows(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        """The per-index aggregate rows behind one scene — the expanded row."""
        sql = f"""
            SELECT a.index_code, a.mean, a.min, a.max, a.p10, a.p50, a.p90,
                   a.std_dev, a.valid_pixel_count, a.total_pixel_count,
                   a.valid_pixel_pct, a.cloud_cover_pct, a.baseline_deviation,
                   a.stac_item_id, a.inserted_at
              FROM block_index_aggregates a
             WHERE a.block_id = :bid
               AND a.product_id = :pid
               AND a.time = {_ts(scene_time)}
             ORDER BY a.index_code
        """
        rows = (
            await self._s.execute(text(sql), {"bid": str(block_id), "pid": str(product_id)})
        ).mappings()
        return [dict(r) for r in rows]

    # ---- L2: scene detail -------------------------------------------------

    async def scene_context(self, job_id: UUID) -> dict[str, Any] | None:
        """Everything needed to open, mask and explain one scene.

        One query rather than four round-trips: the pixel inspector is a
        click-latency interaction, and each of these lookups is on the
        critical path before a single byte of raster is read.

        `provider_code` joins out to `imagery_providers` — `imagery_products`
        does not carry one. The grid config is resolved by the **scene's own
        time**, not "the current grid", so a 2025 scene reports the geometry
        it was actually computed against.
        """
        row = (
            (
                await self._s.execute(
                    text(
                        """
                    SELECT
                      j.id AS job_id, j.block_id, j.product_id, j.scene_id,
                      j.scene_datetime, j.status, j.stac_item_id,
                      j.cloud_cover_pct, j.valid_pixel_pct,
                      j.error_code, j.error_message,
                      j.requested_at, j.started_at, j.completed_at,
                      j.assets_written,
                      b.farm_id, b.code AS block_code, b.name AS block_name,
                      b.aoi_hash, b.area_m2,
                      ST_AsGeoJSON(b.boundary)::text AS boundary_geojson,
                      ST_AsGeoJSON(b.boundary_utm)::text AS boundary_utm_geojson,
                      p.code AS product_code, p.name AS product_name,
                      p.bands, p.supported_indices, p.resolution_m,
                      pr.code AS provider_code, pr.name AS provider_name,
                      cfg.id AS grid_config_id,
                      cfg.cell_size_m, cfg.utm_srid,
                      cfg.effective_from, cfg.effective_to,
                      (SELECT count(*) FROM grid_cells gc
                        WHERE gc.grid_config_id = cfg.id) AS cell_count
                      FROM imagery_ingestion_jobs j
                      JOIN blocks b ON b.id = j.block_id
                      JOIN public.imagery_products p ON p.id = j.product_id
                      JOIN public.imagery_providers pr ON pr.id = p.provider_id
                      LEFT JOIN grid_configs cfg
                             ON cfg.block_id = j.block_id
                            AND cfg.product_id = j.product_id
                            AND cfg.deleted_at IS NULL
                            AND cfg.superseded_at IS NULL
                            AND tstzrange(cfg.effective_from, cfg.effective_to)
                                @> j.scene_datetime
                     WHERE j.id = :jid
                       AND b.deleted_at IS NULL
                    """
                    ),
                    {"jid": str(job_id)},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def index_formulas(self) -> dict[str, str]:
        """`indices_catalog.formula_text` keyed by code.

        The pixel inspector renders the formula from here rather than from a
        string in the codebase, so there is exactly one place a formula is
        written down and the panel cannot describe maths the pipeline is not
        doing.
        """
        rows = (
            await self._s.execute(text("SELECT code, formula_text FROM public.indices_catalog"))
        ).all()
        return {str(r[0]): str(r[1]) for r in rows}

    # ---- plumbing --------------------------------------------------------

    async def _all(self, sql: str, *, block_ids: list[UUID], product_id: UUID | None) -> list[Any]:
        stmt = text(sql).bindparams(bindparam("bids", expanding=True))
        params: dict[str, Any] = {"bids": [str(b) for b in block_ids]}
        if product_id:
            params["pid"] = str(product_id)
        return list((await self._s.execute(stmt, params)).mappings())

    async def _one(
        self, sql: str, *, block_ids: list[UUID], product_id: UUID | None
    ) -> dict[str, Any]:
        rows = await self._all(sql, block_ids=block_ids, product_id=product_id)
        return dict(rows[0])

    async def cells_for_scene(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        """Grid cells governing this scene's time, with their stored aggregate.

        LEFT JOIN on the aggregate: a cell that exists but produced no row is
        the interesting case — it means the zonal pass skipped it — and an
        inner join would hide exactly that.

        Geometry comes back in WGS84 for the map, and the WKT stays in the
        cell's own UTM so the drill-down can hand it to `geometry_mask`
        against a raster in the same projection, which is how the pipeline
        does it.
        """
        sql = f"""
            SELECT gc.id AS cell_id, gc.row_idx, gc.col_idx,
                   ST_AsGeoJSON(ST_Transform(gc.geom, 4326))::text AS geometry,
                   ST_AsText(gc.geom) AS geom_wkt,
                   gc.area_m2,
                   a.mean, a.min, a.max, a.std_dev,
                   a.valid_pixel_count, a.total_pixel_count
              FROM grid_cells gc
              JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
              LEFT JOIN block_grid_aggregates a
                     ON a.cell_id = gc.id
                    AND a.index_code = :code
                    AND a.product_id = :pid
                    AND a.time = {_ts(scene_time)}
             WHERE cfg.block_id = :bid
               AND cfg.product_id = :pid
               AND cfg.deleted_at IS NULL
               AND cfg.superseded_at IS NULL
               AND tstzrange(cfg.effective_from, cfg.effective_to) @> {_ts(scene_time)}
             ORDER BY gc.row_idx, gc.col_idx
        """
        rows = (
            await self._s.execute(
                text(sql),
                {"bid": str(block_id), "pid": str(product_id), "code": index_code},
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def cell_by_id(self, cell_id: UUID) -> dict[str, Any] | None:
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT gc.id AS cell_id, gc.row_idx, gc.col_idx,
                           ST_AsText(gc.geom) AS geom_wkt,
                           ST_AsGeoJSON(ST_Transform(gc.geom, 4326))::text AS geometry
                      FROM grid_cells gc
                     WHERE gc.id = :cid
                    """
                ),
                {"cid": str(cell_id)},
            )
        ).mappings()
        found = rows.first()
        return dict(found) if found else None


def get_observer_repository(session: AsyncSession) -> ObserverRepository:
    return ObserverRepository(session)
