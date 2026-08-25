"""Read-only integration health service.

Queries the `v_farm_integration_health` / `v_block_integration_health`
views (created by tenant migration 0019 + extended in 0022) and the
`v_integration_recent_attempts` union view (added in 0022). All views
run in the tenant schema — the caller is expected to set search_path
before invocation, which is what `requires_capability` already arranges
via the auth middleware.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Columns are listed explicitly so adding view columns can't accidentally
# break the API contract — we'd see the schema mismatch immediately.
_FARM_COLUMNS = (
    "farm_id, farm_name, "
    "weather_active_subs, weather_last_sync_at, weather_last_failed_at, "
    "imagery_active_subs, imagery_last_sync_at, imagery_failed_24h, "
    "weather_failed_24h, weather_running_count, imagery_running_count, "
    "weather_overdue_count, imagery_overdue_count"
)
# `v.block_name` is `blocks.name`, which is NULLABLE — bulk-created blocks
# routinely have none. Fall back to the code the way every other module that
# labels a block does (insights/service.py, reports/service.py); returning
# NULL here failed response validation and 500'd the whole endpoint.
_BLOCK_COLUMNS = (
    "v.block_id, v.farm_id, COALESCE(v.block_name, b.code) AS block_name, "
    "v.weather_active_subs, v.weather_last_sync_at, v.weather_last_failed_at, "
    "v.imagery_active_subs, v.imagery_last_sync_at, v.imagery_failed_24h, "
    "v.weather_failed_24h, v.weather_running_count, v.imagery_running_count, "
    "v.weather_overdue_count, v.imagery_overdue_count"
)
_ATTEMPT_COLUMNS = (
    "attempt_id, kind, scope, subscription_id, block_id, farm_id, provider_code, "
    "started_at, queued_at, completed_at, status, "
    "duration_ms, wait_ms, run_ms, rows_ingested, "
    "error_code, error_message, scene_id, failed_streak_position"
)


class IntegrationsHealthService:
    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._tenant = tenant_session

    async def list_farms(self) -> list[dict[str, Any]]:
        rows = (
            (
                await self._tenant.execute(
                    text(
                        f"""
                    SELECT {_FARM_COLUMNS}
                    FROM v_farm_integration_health
                    ORDER BY farm_name
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def list_blocks(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        rows = (
            (
                await self._tenant.execute(
                    text(
                        f"""
                    SELECT {_BLOCK_COLUMNS}
                    FROM v_block_integration_health v
                    JOIN blocks b ON b.id = v.block_id
                    WHERE v.farm_id = :fid
                    ORDER BY block_name
                    """
                    ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                    {"fid": farm_id},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    # ---- Drill-down (PR-IH3) -----------------------------------------

    async def list_block_attempts(
        self,
        *,
        block_id: UUID,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Recent ingestion attempts for one block, newest first.

        `kind` filters 'weather'|'imagery'; None returns both interleaved.

        Includes the farm-scoped attempts of the block's own farm. A block
        covered by a whole-farm subscription has no attempt rows of its own
        — that is the entire point of the farm path — so matching on
        `block_id` alone returns an empty run log for a block that is being
        ingested every day. The farm rows carry `scope = 'farm'`, so a
        reader can still tell which acquisition covered it.
        """
        clauses = [
            """(
                block_id = :block_id
                OR (scope = 'farm'
                    AND farm_id = (SELECT b.farm_id FROM blocks b
                                    WHERE b.id = :block_id))
            )"""
        ]
        params: dict[str, Any] = {"block_id": block_id, "limit": max(1, min(limit, 500))}
        if kind is not None:
            clauses.append("kind = :kind")
            params["kind"] = kind
        rows = (
            (
                await self._tenant.execute(
                    text(
                        f"""
                    SELECT {_ATTEMPT_COLUMNS}
                    FROM v_integration_recent_attempts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY started_at DESC
                    LIMIT :limit
                    """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    # ---- Queue (PR-IH4) ----------------------------------------------

    async def list_queue(
        self,
        *,
        kind: str | None = None,
        state: str | None = None,
        stuck_minutes: int = 30,
        default_weather_cadence_hours: int = 3,
        default_imagery_cadence_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return one row per (subscription, queue state).

        `state` filters: 'overdue' | 'running' | 'stuck' (or None for all).
        A subscription can appear in multiple states (overdue + stuck on
        the same row's most recent attempt) — that's fine; the UI groups
        by state and shows the row once per group.

        Stuck-threshold is in minutes, defaulting to 30. Callers expose
        this via `platform_defaults` in PR-IH4+; for now it's a kwarg.
        """
        rows: list[dict[str, Any]] = []
        wants_weather = kind is None or kind == "weather"
        wants_imagery = kind is None or kind == "imagery"

        # --- Weather --------------------------------------------------
        if wants_weather and (state is None or state == "overdue"):
            r = (
                (
                    await self._tenant.execute(
                        text(
                            """
                        -- A farm with its own weather subscription is
                        -- monitored through that row; its block rows are
                        -- skipped so one stale farm does not report once per
                        -- block. Farms with no farm row still report per
                        -- block, which is what keeps the cutover gradual.
                        SELECT 'block'::text AS scope,
                               ws.id AS subscription_id,
                               ws.block_id,
                               b.code AS block_code,
                               b.farm_id,
                               (SELECT f2.name FROM farms f2
                                 WHERE f2.id = b.farm_id) AS farm_name,
                               ws.provider_code,
                               ws.last_successful_ingest_at AS since
                        FROM weather_subscriptions ws
                        JOIN blocks b ON b.id = ws.block_id
                        WHERE ws.is_active
                          AND ws.deleted_at IS NULL
                          AND b.deleted_at IS NULL
                          AND NOT EXISTS (
                              SELECT 1 FROM weather_farm_subscriptions wfs
                              WHERE wfs.farm_id = b.farm_id
                                AND wfs.provider_code = ws.provider_code
                                AND wfs.is_active AND wfs.deleted_at IS NULL
                          )
                          AND (ws.last_successful_ingest_at IS NULL
                               OR ws.last_successful_ingest_at <
                                  now() - make_interval(
                                    hours => COALESCE(ws.cadence_hours,
                                                      :default_cadence)))

                        UNION ALL

                        SELECT 'farm'::text AS scope,
                               wfs.id AS subscription_id,
                               NULL::uuid AS block_id,
                               NULL::text AS block_code,
                               wfs.farm_id,
                               f.name AS farm_name,
                               wfs.provider_code,
                               wfs.last_successful_ingest_at AS since
                        FROM weather_farm_subscriptions wfs
                        JOIN farms f ON f.id = wfs.farm_id
                        WHERE wfs.is_active
                          AND wfs.deleted_at IS NULL
                          AND f.deleted_at IS NULL
                          AND (wfs.last_successful_ingest_at IS NULL
                               OR wfs.last_successful_ingest_at <
                                  now() - make_interval(
                                    hours => COALESCE(wfs.cadence_hours,
                                                      :default_cadence)))
                        ORDER BY since NULLS FIRST
                        """
                        ),
                        {"default_cadence": default_weather_cadence_hours},
                    )
                )
                .mappings()
                .all()
            )
            for x in r:
                d = dict(x)
                d.update({"kind": "weather", "state": "overdue", "attempt_id": None})
                rows.append(d)

        if wants_weather and (state is None or state in ("running", "stuck")):
            r = (
                (
                    await self._tenant.execute(
                        text(
                            """
                        SELECT wa.id AS attempt_id,
                               -- 0077: a farm-scoped attempt leaves
                               -- block_id NULL. Naming it here keeps the
                               -- UI off a null-check.
                               CASE WHEN wa.block_id IS NULL
                                    THEN 'farm' ELSE 'block' END AS scope,
                               wa.subscription_id,
                               wa.block_id,
                               (SELECT b.code FROM blocks b
                                 WHERE b.id = wa.block_id) AS block_code,
                               wa.farm_id,
                               (SELECT f.name FROM farms f
                                 WHERE f.id = wa.farm_id) AS farm_name,
                               wa.provider_code,
                               wa.started_at AS since
                        FROM weather_ingestion_attempts wa
                        WHERE wa.status = 'running'
                        ORDER BY wa.started_at ASC
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
            stuck_cutoff_sql = "EXTRACT(EPOCH FROM (now() - wa.started_at)) / 60 >= :stuck_minutes"
            for x in r:
                d = dict(x)
                # Determine state per row in Python — re-running the query
                # twice for stuck vs not-stuck is wasteful.
                from datetime import datetime as _dt

                age_min = (_dt.now(UTC) - d["since"]).total_seconds() / 60
                row_state = "stuck" if age_min >= stuck_minutes else "running"
                if state is None or state == row_state:
                    d.update({"kind": "weather", "state": row_state})
                    rows.append(d)
            _ = stuck_cutoff_sql  # silence unused-var warning

        # --- Imagery --------------------------------------------------
        if wants_imagery and (state is None or state == "overdue"):
            r = (
                (
                    await self._tenant.execute(
                        text(
                            """
                        -- Block subscriptions, and FARM ones for farms that
                        -- have cut over. Without the second half, switching a
                        -- farm to farm-AOI fetching would drop it out of this
                        -- scan entirely: the block rows go inactive, nothing
                        -- replaces them, and the farm reads as healthy while
                        -- its imagery quietly stops. A monitoring blind spot
                        -- is worse than a false alarm.
                        SELECT 'block'::text AS scope,
                               ias.id AS subscription_id,
                               ias.block_id,
                               b.code AS block_code,
                               b.farm_id,
                               (SELECT f2.name FROM farms f2
                                 WHERE f2.id = b.farm_id) AS farm_name,
                               (SELECT ip.code FROM public.imagery_products ip
                                WHERE ip.id = ias.product_id) AS provider_code,
                               ias.last_successful_ingest_at AS since
                        FROM imagery_aoi_subscriptions ias
                        JOIN blocks b ON b.id = ias.block_id
                        WHERE ias.is_active
                          AND ias.deleted_at IS NULL
                          AND b.deleted_at IS NULL
                          -- Same exclusion the weather arm above makes, and
                          -- the same one `list_active_subscriptions_due`
                          -- makes: once a farm fetches this product as one
                          -- AOI, its block rows stop being polled and their
                          -- watermarks freeze, so every one of them would
                          -- read overdue for ever. The farm arm below is
                          -- what monitors those farms.
                          AND NOT EXISTS (
                              SELECT 1 FROM imagery_farm_subscriptions ifs
                              WHERE ifs.farm_id = b.farm_id
                                AND ifs.product_id = ias.product_id
                                AND ifs.is_active
                                AND ifs.fetch_farm_aoi
                                AND ifs.deleted_at IS NULL
                          )
                          AND (ias.last_successful_ingest_at IS NULL
                               OR ias.last_successful_ingest_at <
                                  now() - make_interval(
                                    hours => COALESCE(ias.cadence_hours,
                                                      :default_cadence)))

                        UNION ALL

                        SELECT 'farm'::text AS scope,
                               ifs.id AS subscription_id,
                               NULL::uuid AS block_id,
                               NULL::text AS block_code,
                               ifs.farm_id,
                               f.name AS farm_name,
                               (SELECT ip.code FROM public.imagery_products ip
                                WHERE ip.id = ifs.product_id) AS provider_code,
                               ifs.last_successful_ingest_at AS since
                        FROM imagery_farm_subscriptions ifs
                        JOIN farms f ON f.id = ifs.farm_id
                        WHERE ifs.is_active
                          AND ifs.fetch_farm_aoi
                          AND ifs.deleted_at IS NULL
                          AND f.deleted_at IS NULL
                          AND (ifs.last_successful_ingest_at IS NULL
                               OR ifs.last_successful_ingest_at <
                                  now() - make_interval(
                                    hours => COALESCE(ifs.cadence_hours,
                                                      :default_cadence)))
                        ORDER BY since NULLS FIRST
                        """
                        ),
                        {"default_cadence": default_imagery_cadence_hours},
                    )
                )
                .mappings()
                .all()
            )
            for x in r:
                d = dict(x)
                d.update({"kind": "imagery", "state": "overdue", "attempt_id": None})
                rows.append(d)

        if wants_imagery and (state is None or state in ("running", "stuck")):
            r = (
                (
                    await self._tenant.execute(
                        text(
                            """
                        SELECT ij.id AS attempt_id,
                               'block'::text AS scope,
                               ij.subscription_id,
                               ij.block_id,
                               b.code AS block_code,
                               b.farm_id,
                               (SELECT f2.name FROM farms f2
                                 WHERE f2.id = b.farm_id) AS farm_name,
                               (SELECT ip.code FROM public.imagery_products ip
                                WHERE ip.id = ij.product_id) AS provider_code,
                               COALESCE(ij.started_at, ij.requested_at) AS since
                        FROM imagery_ingestion_jobs ij
                        JOIN blocks b ON b.id = ij.block_id
                        WHERE ij.status IN ('pending', 'requested', 'running')
                          AND b.deleted_at IS NULL

                        UNION ALL

                        -- The farm path has its own job table (0076). Left
                        -- out, a farm whose whole-AOI fetches are wedged
                        -- shows an EMPTY queue — the one state the queue
                        -- exists to make visible. On prod 2026-08-17 that
                        -- was 51 pending/running farm jobs invisible here,
                        -- all of the tenant's thermal work among them.
                        SELECT fj.id AS attempt_id,
                               'farm'::text AS scope,
                               fj.subscription_id,
                               NULL::uuid AS block_id,
                               NULL::text AS block_code,
                               fj.farm_id,
                               f.name AS farm_name,
                               (SELECT ip.code FROM public.imagery_products ip
                                WHERE ip.id = fj.product_id) AS provider_code,
                               COALESCE(fj.started_at, fj.requested_at) AS since
                        FROM imagery_farm_ingestion_jobs fj
                        JOIN farms f ON f.id = fj.farm_id
                        WHERE fj.status IN ('pending', 'requested', 'running')
                          AND f.deleted_at IS NULL
                        ORDER BY since ASC
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
            for x in r:
                d = dict(x)
                from datetime import datetime as _dt

                age_min = (_dt.now(UTC) - d["since"]).total_seconds() / 60
                row_state = "stuck" if age_min >= stuck_minutes else "running"
                if state is None or state == row_state:
                    d.update({"kind": "imagery", "state": row_state})
                    rows.append(d)

        return rows

    async def list_recent_attempts(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        farm_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Recent attempts across the tenant, newest first. Filterable."""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if kind is not None:
            clauses.append("kind = :kind")
            params["kind"] = kind
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if farm_id is not None:
            clauses.append("farm_id = :farm_id")
            params["farm_id"] = farm_id
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        stmt = text(
            f"""
            SELECT {_ATTEMPT_COLUMNS}
            FROM v_integration_recent_attempts
            {where}
            ORDER BY started_at DESC
            LIMIT :limit
            """
        )
        if farm_id is not None:
            stmt = stmt.bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return [dict(r) for r in rows]


def get_integrations_health_service(
    tenant_session: AsyncSession,
) -> IntegrationsHealthService:
    return IntegrationsHealthService(tenant_session=tenant_session)
