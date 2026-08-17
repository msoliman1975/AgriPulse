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

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# Every job status Observer can be asked to filter on, across BOTH job
# tables. Mirrored here because Observer groups by them; a status added
# upstream without updating this constant would silently vanish from the
# histogram and become unselectable in the scene filter, so
# `test_job_status_constant_matches_check_constraint` pins it.
#
# The first six are the CHECK on `imagery_ingestion_jobs` (tenant 0003).
# `skipped` belongs to `imagery_farm_ingestion_jobs` (tenant 0076), which
# skips without saying why — the farm path is the only writer of it, and
# leaving it out made every skipped thermal scene unfilterable.
JOB_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped_cloud",
    "skipped_duplicate",
    "skipped",
)

# The farm table's own vocabulary — the part of `JOB_STATUSES` that the
# block CHECK does not declare. Split out so the drift guard can still
# compare the block half against the migration exactly.
FARM_ONLY_JOB_STATUSES: frozenset[str] = frozenset({"skipped"})

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


def _d(value: date) -> str:
    """Render a date as a SQL date literal, for the same reason as `_ts`.

    `datetime` is a subclass of `date`, so the check is deliberately ordered
    to reject it: a datetime reaching a `DATE` literal would silently drop its
    time component, which is exactly the class of bug this module exists to
    surface.
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"day bound must be a date, got {type(value).__name__}")
    return f"DATE '{value.isoformat()}'"


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
                      -- A farm fetching its own AOI covers every one of its
                      -- blocks with a single subscription, so counting only
                      -- per-block rows would show a cut-over farm as having
                      -- no imagery at all.
                      (CASE WHEN EXISTS (
                              SELECT 1 FROM imagery_farm_subscriptions fs
                               WHERE fs.farm_id = f.id
                                 AND fs.is_active = TRUE
                                 AND fs.fetch_farm_aoi = TRUE
                                 AND fs.deleted_at IS NULL)
                            THEN (SELECT count(*) FROM blocks b
                                   WHERE b.farm_id = f.id AND b.deleted_at IS NULL)
                            ELSE (SELECT count(DISTINCT s.block_id)
                                    FROM imagery_aoi_subscriptions s
                                    JOIN blocks b ON b.id = s.block_id
                                   WHERE b.farm_id = f.id
                                     AND b.deleted_at IS NULL
                                     AND s.is_active = TRUE
                                     AND s.deleted_at IS NULL)
                       END) AS blocks_with_imagery_sub,
                      (SELECT count(DISTINCT g.block_id)
                         FROM grid_configs g
                         JOIN blocks b ON b.id = g.block_id
                        WHERE b.farm_id = f.id
                          AND b.deleted_at IS NULL
                          AND g.retired_at IS NULL
                          AND g.deleted_at IS NULL) AS blocks_with_grid,
                      (EXISTS (SELECT 1 FROM weather_subscriptions w
                                JOIN blocks b ON b.id = w.block_id
                               WHERE b.farm_id = f.id
                                 AND w.is_active = TRUE
                                 AND w.deleted_at IS NULL)
                       OR EXISTS (SELECT 1 FROM weather_farm_subscriptions wf
                                   WHERE wf.farm_id = f.id
                                     AND wf.is_active = TRUE
                                     AND wf.deleted_at IS NULL)) AS has_weather_sub,
                      -- Scene range spans both acquisition paths, or a farm
                      -- cut over to farm-AOI fetching reads as never having
                      -- had a scene.
                      (SELECT min(t) FROM (
                          SELECT j.scene_datetime AS t FROM imagery_ingestion_jobs j
                            JOIN blocks b ON b.id = j.block_id
                           WHERE b.farm_id = f.id
                          UNION ALL
                          SELECT fj.scene_datetime FROM imagery_farm_ingestion_jobs fj
                           WHERE fj.farm_id = f.id
                       ) x) AS first_scene_at,
                      (SELECT max(t) FROM (
                          SELECT j.scene_datetime AS t FROM imagery_ingestion_jobs j
                            JOIN blocks b ON b.id = j.block_id
                           WHERE b.farm_id = f.id
                          UNION ALL
                          SELECT fj.scene_datetime FROM imagery_farm_ingestion_jobs fj
                           WHERE fj.farm_id = f.id
                       ) x) AS last_scene_at
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
                        UNION
                        -- The farm path, or the product picker would offer
                        -- nothing for a farm that only ever fetched its AOI —
                        -- and an empty picker reads as "no data".
                        SELECT DISTINCT fj.product_id
                          FROM imagery_farm_ingestion_jobs fj
                         WHERE fj.farm_id = :fid
                        UNION
                        SELECT DISTINCT fs.product_id
                          FROM imagery_farm_subscriptions fs
                         WHERE fs.farm_id = :fid AND fs.deleted_at IS NULL
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

    async def stage_problem_scenes(
        self,
        *,
        farm_id: UUID,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """The acquisitions behind a shortfall, with what actually went wrong.

        The ribbon could say "2 scenes were discovered but never downloaded"
        and then send the reader to hunt through the scene list for a cause.
        Worse, it *asserted* the cause — "check the provider errors" — when
        on the farm that prompted this the two scenes carried no error at
        all: they were still `running`, requested hours earlier and stuck.
        A diagnosis that names the wrong cause is worse than one that names
        none.

        So this returns the rows themselves: every non-succeeded acquisition
        in the window, from both paths, with its status, error code and
        message. Succeeded-but-computed-nothing is included too — that is
        the `indices` shortfall, and it is invisible in the job status.

        `blocked_reason` is derived here rather than in the UI because it
        depends on which table the row came from and how its status maps.
        """
        prod_block = "AND j.product_id = :pid" if product_id else ""
        prod_farm = "AND f.product_id = :pid" if product_id else ""
        sql = f"""
            WITH acquisitions AS (
                SELECT 'block'::text AS scope,
                       j.id AS job_id,
                       COALESCE(b.name, b.code) AS label,
                       j.scene_id, j.scene_datetime, j.status,
                       j.error_code, j.error_message,
                       j.block_id, j.product_id,
                       j.requested_at, j.started_at, j.completed_at
                  FROM imagery_ingestion_jobs j
                  JOIN blocks b ON b.id = j.block_id
                 WHERE j.block_id IN :bids
                   {prod_block}
                   AND j.scene_datetime >= {_ts(window_from)}
                   AND j.scene_datetime < {_ts(window_to)}

                UNION ALL

                SELECT 'farm'::text AS scope,
                       f.id AS job_id,
                       fm.name AS label,
                       f.scene_id, f.scene_datetime, f.status,
                       f.error_code, f.error_message,
                       NULL::uuid AS block_id, f.product_id,
                       f.requested_at, f.started_at, f.completed_at
                  FROM imagery_farm_ingestion_jobs f
                  JOIN farms fm ON fm.id = f.farm_id
                 WHERE f.farm_id = :fid
                   {prod_farm}
                   AND f.scene_datetime >= {_ts(window_from)}
                   AND f.scene_datetime < {_ts(window_to)}
            ),
            judged AS (
                SELECT a.*,
                       EXISTS (
                         SELECT 1 FROM block_index_aggregates agg
                          WHERE agg.block_id IN :bids
                            AND agg.product_id = a.product_id
                            AND agg.time = a.scene_datetime
                            AND agg.time >= {_ts(window_from)}
                            AND agg.time < {_ts(window_to)}
                       ) AS has_aggregates
                  FROM acquisitions a
            )
            SELECT scope, job_id, label, scene_id, scene_datetime, status,
                   error_code, error_message, block_id,
                   requested_at, started_at, completed_at, has_aggregates,
                   CASE
                     WHEN status = 'failed' THEN 'failed'
                     WHEN status IN ('pending', 'requested', 'running') THEN 'in_flight'
                     WHEN status IN ('skipped_cloud', 'skipped_duplicate', 'skipped')
                       THEN 'skipped'
                     WHEN status = 'succeeded' AND NOT has_aggregates
                       THEN 'no_aggregates'
                     ELSE 'ok'
                   END AS problem
              FROM judged
             WHERE status <> 'succeeded' OR NOT has_aggregates
             ORDER BY scene_datetime DESC
             LIMIT :limit
        """  # noqa: S608
        stmt = text(sql).bindparams(bindparam("bids", expanding=True))
        params: dict[str, Any] = {
            "bids": [str(b) for b in block_ids],
            "fid": str(farm_id),
            "limit": max(1, min(limit, 200)),
        }
        if product_id:
            params["pid"] = str(product_id)
        rows = (await self._s.execute(stmt, params)).mappings()
        return [dict(r) for r in rows]

    async def job_stage_counts(
        self,
        *,
        farm_id: UUID,
        block_ids: list[UUID],
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, int]:
        """Counts for the first three ribbon stages, in one pass.

        Counts BOTH acquisition paths. A farm fetching its own AOI writes no
        per-block jobs at all, so reading only `imagery_ingestion_jobs` would
        report zero scenes acquired for a cut-over farm while its indices
        kept appearing — "indices from nowhere", which reads as a defect in
        the pipeline rather than a gap in the observer.

        The two tables do not share a status vocabulary: a block job skips as
        `skipped_cloud` / `skipped_duplicate`, a farm job simply as
        `skipped`. Both are folded into the same bucket here, because to a
        reader of the ribbon they are the same event.

        A farm job is one acquisition covering every block, where the block
        path wrote one per block. The counts are therefore acquisitions, not
        block-scenes — which is what the ribbon has always meant.
        """
        prod_block = "AND j.product_id = :pid" if product_id else ""
        prod_farm = "AND f.product_id = :pid" if product_id else ""
        sql = f"""
            WITH acquisitions AS (
                SELECT j.status, j.stac_item_id
                  FROM imagery_ingestion_jobs j
                 WHERE j.block_id IN :bids
                   {prod_block}
                   AND j.scene_datetime >= {_ts(window_from)}
                   AND j.scene_datetime < {_ts(window_to)}

                UNION ALL

                SELECT f.status, f.stac_item_id
                  FROM imagery_farm_ingestion_jobs f
                 WHERE f.farm_id = :fid
                   {prod_farm}
                   AND f.scene_datetime >= {_ts(window_from)}
                   AND f.scene_datetime < {_ts(window_to)}
            )
            SELECT
              count(*) AS discovered,
              count(*) FILTER (
                WHERE status = 'succeeded' AND stac_item_id IS NOT NULL
              ) AS acquired,
              count(*) FILTER (WHERE status = 'failed') AS failed,
              count(*) FILTER (WHERE status IN ('pending', 'running')) AS in_flight,
              count(*) FILTER (
                WHERE status IN ('skipped_cloud', 'skipped_duplicate', 'skipped')
              ) AS skipped
              FROM acquisitions
        """  # noqa: S608
        row = await self._one(sql, block_ids=block_ids, product_id=product_id, farm_id=farm_id)
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
        farm_id: UUID,
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

        Both acquisition paths contribute to the denominator. A farm job
        covers every block in scope, so it is expected to produce one
        (scene, block, product) cell-aggregate group per *gridded* block —
        which is why the farm arm joins out to the blocks rather than
        counting the job once. Left out, a cut-over farm's produced count
        stayed high while its expected count fell to zero, and the stage
        reported `not_applicable` on a farm whose cells were being written
        every day.
        """
        prod_a = "AND a.product_id = :pid" if product_id else ""
        prod_j = "AND j.product_id = :pid" if product_id else ""
        prod_f = "AND f.product_id = :pid" if product_id else ""
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

                 UNION

                 SELECT DISTINCT f.scene_datetime, cfg.block_id, f.product_id
                   FROM imagery_farm_ingestion_jobs f
                   JOIN grid_configs cfg
                     ON cfg.block_id IN :bids
                    AND cfg.product_id = f.product_id
                    AND cfg.deleted_at IS NULL
                    AND cfg.superseded_at IS NULL
                    AND tstzrange(cfg.effective_from, cfg.effective_to)
                        @> f.scene_datetime
                  WHERE f.farm_id = :fid
                    {prod_f}
                    AND f.status = 'succeeded'
                    AND f.scene_datetime >= {_ts(window_from)}
                    AND f.scene_datetime < {_ts(window_to)}
               ) e) AS expected
        """  # noqa: S608
        row = await self._one(sql, block_ids=block_ids, product_id=product_id, farm_id=farm_id)
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
        block_id: UUID | None,
        product_id: UUID,
        scene_time: datetime,
        farm_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Every recorded execution for one scene, newest first.

        This is what makes a silent overwrite visible. Aggregate rows are
        upserted on their composite key, so a recompute replaces the numbers
        with no trace; the run rows accumulate instead, and two of them with
        different `calc_version` values is the signature of exactly that.

        Pass `farm_id` instead of `block_id` for a whole-farm acquisition.
        The runs are still written per block — only the *fetch* is farm-wide
        — so this returns every block's run for that scene, which is what the
        one acquisition actually caused.
        """
        if block_id is not None:
            scope_clause = "r.block_id = :bid"
            params = {"bid": str(block_id), "pid": str(product_id)}
        elif farm_id is not None:
            scope_clause = """r.block_id IN (
                SELECT b.id FROM blocks b
                 WHERE b.farm_id = :fid AND b.deleted_at IS NULL
            )"""
            params = {"fid": str(farm_id), "pid": str(product_id)}
        else:
            raise ValueError("scene_calc_history needs a block_id or a farm_id")

        sql = f"""
            SELECT r.id, r.job_id, r.calc_version, r.mask_ruleset,
                   r.trigger, r.outcome, r.error,
                   r.aoi_pixel_count, r.masked_pixel_count,
                   r.cell_count, r.grid_config_id, r.band_order,
                   r.per_index, r.started_at, r.completed_at, r.duration_ms,
                   r.created_at
              FROM indices_calc_runs r
             WHERE {scope_clause}
               AND r.product_id = :pid
               AND r.scene_time = {_ts(scene_time)}
             -- `id` breaks the tie: `created_at` defaults to now(), which is
             -- the *transaction* timestamp, so two runs recorded in one
             -- transaction share it exactly. uuid_generate_v7 is
             -- time-ordered, which makes this ordering total.
             ORDER BY r.created_at DESC, r.id DESC
        """
        rows = (await self._s.execute(text(sql), params)).mappings()
        return [dict(r) for r in rows]

    # ---- L0: histogram ---------------------------------------------------

    async def scene_histogram(
        self,
        *,
        farm_id: UUID,
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

        Counts BOTH acquisition paths, like `job_stage_counts` above. A farm
        fetching its own AOI writes nothing to `imagery_ingestion_jobs`, so
        reading only that table left the histogram empty for a cut-over farm
        while the ribbon over it counted the same scenes — the two disagreeing
        on one screen. `landsat_c2_l2_st` is the extreme case: thermal is
        farm-AOI only by construction, so it has never had a single bar here.

        A farm job's `computed` test asks whether ANY block in scope got
        aggregates at that (product, time). One farm acquisition fans out to
        every block, so per-block presence is not the question — "did this
        acquisition produce indices at all" is.
        """
        trunc = BUCKETS[bucket]  # KeyError is a programmer error; router validates
        prod_block = "AND j.product_id = :pid" if product_id else ""
        prod_farm = "AND f.product_id = :pid" if product_id else ""
        sql = f"""
            WITH acquisitions AS (
                SELECT j.status, j.scene_datetime,
                       EXISTS (
                         SELECT 1 FROM block_index_aggregates a
                          WHERE a.block_id = j.block_id
                            AND a.product_id = j.product_id
                            AND a.time = j.scene_datetime
                            AND a.time >= {_ts(window_from)}
                            AND a.time < {_ts(window_to)}
                       ) AS computed
                  FROM imagery_ingestion_jobs j
                 WHERE j.block_id IN :bids
                   {prod_block}
                   AND j.scene_datetime >= {_ts(window_from)}
                   AND j.scene_datetime < {_ts(window_to)}

                UNION ALL

                SELECT f.status, f.scene_datetime,
                       EXISTS (
                         SELECT 1 FROM block_index_aggregates a
                          WHERE a.block_id IN :bids
                            AND a.product_id = f.product_id
                            AND a.time = f.scene_datetime
                            AND a.time >= {_ts(window_from)}
                            AND a.time < {_ts(window_to)}
                       ) AS computed
                  FROM imagery_farm_ingestion_jobs f
                 WHERE f.farm_id = :fid
                   {prod_farm}
                   AND f.scene_datetime >= {_ts(window_from)}
                   AND f.scene_datetime < {_ts(window_to)}
            )
            SELECT
              date_trunc('{trunc}', scene_datetime) AS bucket,
              count(*) FILTER (WHERE status = 'succeeded' AND computed) AS computed,
              count(*) FILTER (WHERE status = 'succeeded' AND NOT computed)
                AS acquired_only,
              -- A block job skips as 'skipped_cloud'/'skipped_duplicate', a
              -- farm job as plain 'skipped'. Same event to a reader of a bar.
              count(*) FILTER (
                WHERE status IN ('skipped_cloud', 'skipped_duplicate', 'skipped')
              ) AS skipped,
              count(*) FILTER (WHERE status = 'failed') AS failed,
              count(*) FILTER (WHERE status IN ('pending', 'running')) AS pending,
              count(*) AS total
              FROM acquisitions
             GROUP BY 1
             ORDER BY 1
        """  # noqa: S608
        rows = await self._all(sql, block_ids=block_ids, product_id=product_id, farm_id=farm_id)
        return [dict(r) for r in rows]

    # ---- L1: scene table -------------------------------------------------

    async def list_scenes(
        self,
        *,
        farm_id: UUID,
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
        """One row per acquisition, with what each stage produced.

        An acquisition is a block job OR a farm job — the same union the
        ribbon and the histogram count. Without the farm arm this table was
        empty for a cut-over farm while the ribbon above it reported dozens of
        scenes acquired, and thermal (`landsat_c2_l2_st`, farm-AOI only) had
        no row here at any time in its life.

        A farm row carries `scope = 'farm'` and a NULL `block_id`: one
        acquisition covers every block, so naming one of them would be a
        fiction. Its `indices_written` / `cells_written` are therefore summed
        across the farm's blocks in scope, where a block row counts only its
        own.

        `indices_written` and `cells_written` come from LEFT JOINs, never
        inner ones: a job with no aggregates must appear with a zero, since
        that is exactly the row an operator opens this table to find.

        `max_valid_pct` filters block rows only. `imagery_farm_ingestion_jobs`
        records no `valid_pixel_pct`, and treating "not measured" as 0 would
        put every farm scene at the top of a "worst valid pixels" filter.
        """
        prod = "AND j.product_id = :pid" if product_id else ""
        prod_farm = "AND fj.product_id = :pid" if product_id else ""
        filters = ""
        farm_filters = ""
        params: dict[str, Any] = {}
        if statuses:
            filters += " AND j.status IN :statuses"
            farm_filters += " AND fj.status IN :statuses"
            params["statuses"] = statuses
        if max_valid_pct is not None:
            filters += " AND j.valid_pixel_pct IS NOT NULL AND j.valid_pixel_pct < :maxvp"
            # No such column on the farm table — see the docstring. Excluding
            # the arm outright beats inventing a value for it.
            farm_filters += " AND FALSE"
            params["maxvp"] = max_valid_pct
        if with_error:
            filters += " AND (j.error_code IS NOT NULL OR j.error_message IS NOT NULL)"
            farm_filters += " AND (fj.error_code IS NOT NULL OR fj.error_message IS NOT NULL)"

        # Page FIRST, then aggregate once per hypertable.
        #
        # The previous shape put the two hypertable counts in the SELECT list as
        # correlated subqueries, so each ran once PER RETURNED ROW -- 200 rows x
        # 2 hypertables. Every one of those probes had to search the whole
        # window's chunks to locate a single `a.time = j.scene_datetime`,
        # because the planner cannot know at plan time which chunk holds that
        # timestamp. Cost therefore grew with rows x chunks: measured on prod
        # (agrosina, 36 blocks) at 7d 0.76s, 30d 1.35s, 90d 12.3s -- and 90d is
        # the UI's default window, so the first thing an operator saw took 12s.
        #
        # Restructured, `page` applies LIMIT/OFFSET first, then each hypertable
        # is scanned ONCE for just that page's (block, product, time) triples.
        # The window literals stay -- they are what gives plan-time chunk
        # exclusion under a generic plan, which is the #378 fix and must not be
        # dropped.
        #
        # `cells_expected` stays correlated on purpose: grid_cells/grid_configs
        # are ordinary tables, not hypertables, so it is a cheap index probe and
        # not worth the extra CTE.
        sql = f"""
            WITH page AS (
              SELECT
                j.id AS job_id,
                'block'::text AS scope,
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
                b.name AS sort_label
                FROM imagery_ingestion_jobs j
                JOIN blocks b ON b.id = j.block_id
               WHERE j.block_id IN :bids
                 {prod}
                 {filters}
                 AND j.scene_datetime >= {_ts(window_from)}
                 AND j.scene_datetime < {_ts(window_to)}

              UNION ALL

              -- The farm acquisition path (0076). `block_name` carries the
              -- farm's own name so the column still says what was fetched;
              -- `scope` is what a reader keys on.
              SELECT
                fj.id AS job_id,
                'farm'::text AS scope,
                NULL::uuid AS block_id,
                f.name AS block_name,
                f.code AS block_code,
                fj.product_id,
                fj.scene_id,
                fj.scene_datetime,
                fj.status,
                fj.cloud_cover_pct,
                NULL::numeric AS valid_pixel_pct,
                fj.error_code,
                fj.error_message,
                fj.stac_item_id,
                fj.started_at,
                fj.completed_at,
                f.name AS sort_label
                FROM imagery_farm_ingestion_jobs fj
                JOIN farms f ON f.id = fj.farm_id
               WHERE fj.farm_id = :fid
                 {prod_farm}
                 {farm_filters}
                 AND fj.scene_datetime >= {_ts(window_from)}
                 AND fj.scene_datetime < {_ts(window_to)}
               ORDER BY scene_datetime DESC, sort_label
               LIMIT :limit OFFSET :offset
            ),
            idx AS (
              SELECT a.block_id, a.product_id, a.time, count(*) AS n
                FROM block_index_aggregates a
               WHERE a.time >= {_ts(window_from)}
                 AND a.time < {_ts(window_to)}
                 AND EXISTS (
                       SELECT 1 FROM page p
                        WHERE p.scope = 'block'
                          AND p.block_id = a.block_id
                          AND p.product_id = a.product_id
                          AND p.scene_datetime = a.time)
               GROUP BY 1, 2, 3
            ),
            cells AS (
              SELECT a.block_id, a.product_id, a.time, count(DISTINCT a.cell_id) AS n
                FROM block_grid_aggregates a
               WHERE a.time >= {_ts(window_from)}
                 AND a.time < {_ts(window_to)}
                 AND EXISTS (
                       SELECT 1 FROM page p
                        WHERE p.scope = 'block'
                          AND p.block_id = a.block_id
                          AND p.product_id = a.product_id
                          AND p.scene_datetime = a.time)
               GROUP BY 1, 2, 3
            ),
            -- Farm rows roll up across every block in scope: one acquisition
            -- produced all of them, so attributing the total to a block would
            -- both understate the row and invent an owner.
            farm_idx AS (
              SELECT a.product_id, a.time, count(*) AS n
                FROM block_index_aggregates a
               WHERE a.block_id IN :bids
                 AND a.time >= {_ts(window_from)}
                 AND a.time < {_ts(window_to)}
                 AND EXISTS (
                       SELECT 1 FROM page p
                        WHERE p.scope = 'farm'
                          AND p.product_id = a.product_id
                          AND p.scene_datetime = a.time)
               GROUP BY 1, 2
            ),
            farm_cells AS (
              SELECT a.product_id, a.time, count(DISTINCT a.cell_id) AS n
                FROM block_grid_aggregates a
               WHERE a.block_id IN :bids
                 AND a.time >= {_ts(window_from)}
                 AND a.time < {_ts(window_to)}
                 AND EXISTS (
                       SELECT 1 FROM page p
                        WHERE p.scope = 'farm'
                          AND p.product_id = a.product_id
                          AND p.scene_datetime = a.time)
               GROUP BY 1, 2
            )
            SELECT
              j.job_id,
              j.scope,
              j.block_id,
              j.block_name,
              j.block_code,
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
              -- The two `a.time` bounds below are redundant SEMANTICALLY -- the
              -- outer WHERE already pins j.scene_datetime to the same window, and
              -- `a.time = j.scene_datetime` correlates to it. They are here for
              -- the PLANNER. asyncpg prepares this statement, so after ~5
              -- executions Postgres switches to a generic plan; under a generic
              -- plan a correlated column reference folds to nothing at plan time,
              -- TimescaleDB cannot exclude chunks, and the planner takes a lock on
              -- every chunk of both hypertables plus their indexes. agrosina has
              -- 495 chunks each, against max_locks_per_transaction = 64, so this
              -- 500s with "out of shared memory". Interpolated literals restore
              -- plan-time chunk exclusion.
              --
              -- The symptom is bistable and that is what makes it confusing: the
              -- first calls get a custom plan and succeed, then every window fails
              -- until the pod restarts. Do not "verify" this with a single request.
              COALESCE(idx.n, farm_idx.n, 0) AS indices_written,
              COALESCE(cells.n, farm_cells.n, 0) AS cells_written,
              -- A farm acquisition is expected to fill every governed cell
              -- on every block in scope, so its denominator is the farm's,
              -- not one block's.
              CASE WHEN j.scope = 'farm' THEN (
                SELECT count(*) FROM grid_cells gc
                  JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                 WHERE cfg.block_id IN :bids
                   AND cfg.product_id = j.product_id
                   AND cfg.deleted_at IS NULL
                   AND cfg.superseded_at IS NULL
                   AND tstzrange(cfg.effective_from, cfg.effective_to)
                       @> j.scene_datetime
              ) ELSE (
                SELECT count(*) FROM grid_cells gc
                  JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                 WHERE cfg.block_id = j.block_id
                   AND cfg.product_id = j.product_id
                   AND cfg.deleted_at IS NULL
                   AND cfg.superseded_at IS NULL
                   AND tstzrange(cfg.effective_from, cfg.effective_to)
                       @> j.scene_datetime
              ) END AS cells_expected
              FROM page j
              LEFT JOIN idx
                     ON idx.block_id = j.block_id
                    AND idx.product_id = j.product_id
                    AND idx.time = j.scene_datetime
              LEFT JOIN cells
                     ON cells.block_id = j.block_id
                    AND cells.product_id = j.product_id
                    AND cells.time = j.scene_datetime
              LEFT JOIN farm_idx
                     ON j.scope = 'farm'
                    AND farm_idx.product_id = j.product_id
                    AND farm_idx.time = j.scene_datetime
              LEFT JOIN farm_cells
                     ON j.scope = 'farm'
                    AND farm_cells.product_id = j.product_id
                    AND farm_cells.time = j.scene_datetime
             ORDER BY j.scene_datetime DESC, j.block_name
        """  # noqa: S608
        params.update({"limit": limit, "offset": offset, "fid": str(farm_id)})
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

    async def farm_scene_index_rows(
        self,
        *,
        farm_id: UUID,
        product_id: UUID,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        """The same rows for a whole-farm acquisition, one per (block, index).

        Deliberately NOT averaged into one row per index. One fetch produced
        a distinct aggregate on every block, and a mean of means over blocks
        of different sizes is a number no part of the pipeline computed and
        nothing else in the product would agree with. Listing them is longer
        and true.

        `block_name` falls back to the code the way every other block-labelling
        query does — `blocks.name` is nullable and bulk-created blocks have
        none.
        """
        sql = f"""
            SELECT a.block_id,
                   COALESCE(b.name, b.code) AS block_name,
                   a.index_code, a.mean, a.min, a.max, a.p10, a.p50, a.p90,
                   a.std_dev, a.valid_pixel_count, a.total_pixel_count,
                   a.valid_pixel_pct, a.cloud_cover_pct, a.baseline_deviation,
                   a.stac_item_id, a.inserted_at
              FROM block_index_aggregates a
              JOIN blocks b ON b.id = a.block_id
             WHERE b.farm_id = :fid
               AND b.deleted_at IS NULL
               AND a.product_id = :pid
               AND a.time = {_ts(scene_time)}
             ORDER BY a.index_code, block_name
        """
        rows = (
            await self._s.execute(text(sql), {"fid": str(farm_id), "pid": str(product_id)})
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

        Tries the block table first, then the farm one. The two are separate
        tables (0076) but a job id is unique across both, so the caller hands
        in one id and gets back whichever acquisition owns it — which is what
        lets a farm scene open in the same detail page as a block scene.
        """
        row = await self._block_scene_context(job_id)
        if row is None:
            row = await self._farm_scene_context(job_id)
        return row

    async def _block_scene_context(self, job_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._s.execute(
                    text(
                        """
                    SELECT
                      'block'::text AS scope,
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

    async def _farm_scene_context(self, job_id: UUID) -> dict[str, Any] | None:
        """The same context for a whole-farm acquisition.

        Column-for-column identical to the block shape so every caller —
        the detail payload, the pixel inspector, verification — works on
        either without branching. The differences are all real ones:

        * The AOI is the farm boundary, and `aoi_hash` is the farm's (0073).
          That pairing is what makes `raw_bands_key` resolve to the object
          the farm fetch actually wrote; using a block's hash here would
          point the inspector at a path nothing has ever written.
        * `block_id` is NULL and `block_code`/`block_name` carry the farm's,
          because the acquisition has no single block.
        * No grid config: a grid belongs to a block, and this scene spans
          all of them. The detail payload renders `grid: null`, which is
          honest — the per-block grids are reachable from each block's own
          scene rows.
        * `valid_pixel_pct` is NULL — the farm job table does not record it.
        """
        row = (
            (
                await self._s.execute(
                    text(
                        """
                    SELECT
                      'farm'::text AS scope,
                      fj.id AS job_id,
                      NULL::uuid AS block_id,
                      fj.product_id, fj.scene_id,
                      fj.scene_datetime, fj.status, fj.stac_item_id,
                      fj.cloud_cover_pct,
                      NULL::numeric AS valid_pixel_pct,
                      fj.error_code, fj.error_message,
                      fj.requested_at, fj.started_at, fj.completed_at,
                      fj.assets_written,
                      fj.farm_id, f.code AS block_code, f.name AS block_name,
                      f.aoi_hash, f.area_m2,
                      ST_AsGeoJSON(f.boundary)::text AS boundary_geojson,
                      ST_AsGeoJSON(f.boundary_utm)::text AS boundary_utm_geojson,
                      p.code AS product_code, p.name AS product_name,
                      p.bands, p.supported_indices, p.resolution_m,
                      pr.code AS provider_code, pr.name AS provider_name,
                      NULL::uuid AS grid_config_id,
                      NULL::numeric AS cell_size_m,
                      NULL::int AS utm_srid,
                      NULL::timestamptz AS effective_from,
                      NULL::timestamptz AS effective_to,
                      NULL::bigint AS cell_count
                      FROM imagery_farm_ingestion_jobs fj
                      JOIN farms f ON f.id = fj.farm_id
                      JOIN public.imagery_products p ON p.id = fj.product_id
                      JOIN public.imagery_providers pr ON pr.id = p.provider_id
                     WHERE fj.id = :jid
                       AND f.deleted_at IS NULL
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

    async def _all(
        self,
        sql: str,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        farm_id: UUID | None = None,
    ) -> list[Any]:
        stmt = text(sql).bindparams(bindparam("bids", expanding=True))
        params: dict[str, Any] = {"bids": [str(b) for b in block_ids]}
        if product_id:
            params["pid"] = str(product_id)
        # Only bound when the query mentions it — a query without :fid would
        # otherwise fail on an unused parameter.
        if farm_id is not None:
            params["fid"] = str(farm_id)
        return list((await self._s.execute(stmt, params)).mappings())

    async def _one(
        self,
        sql: str,
        *,
        block_ids: list[UUID],
        product_id: UUID | None,
        farm_id: UUID | None = None,
    ) -> dict[str, Any]:
        rows = await self._all(sql, block_ids=block_ids, product_id=product_id, farm_id=farm_id)
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
