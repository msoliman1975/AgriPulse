"""Provider liveness service — reads `public.provider_probe_results`.

Two scopes:

- Platform-wide (PlatformAdmin): every active provider in
  `public.{weather,imagery}_providers`, joined with their latest
  probe.
- Tenant-scoped (TenantOwner / TenantAdmin): only the providers this
  tenant has at least one active subscription on. Computed by union-ing
  `weather_subscriptions.provider_code` + the resolved
  `imagery_aoi_subscriptions.product_id → imagery_providers` join.

This module reads only — the writer is `probes.py` which writes from
the Celery beat task.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_LATEST_PROBE_CTE = """
WITH latest AS (
    SELECT DISTINCT ON (provider_kind, provider_code)
           provider_kind, provider_code, probe_at, status,
           latency_ms, error_message
    FROM public.provider_probe_results
    ORDER BY provider_kind, provider_code, probe_at DESC
),
failures_24h AS (
    SELECT provider_kind, provider_code, COUNT(*) AS n
    FROM public.provider_probe_results
    WHERE status IN ('error', 'timeout')
      AND probe_at > now() - interval '24 hours'
    GROUP BY provider_kind, provider_code
)
"""


class ProviderHealthService:
    def __init__(self, *, public_session: AsyncSession) -> None:
        self._pub = public_session

    async def list_platform_providers(self) -> list[dict[str, Any]]:
        """Every active provider in the public catalogs + latest probe."""
        rows = (
            await self._pub.execute(
                text(
                    _LATEST_PROBE_CTE
                    + """
                    SELECT 'weather'::text AS provider_kind,
                           wp.code AS provider_code,
                           latest.status AS last_status,
                           latest.probe_at AS last_probe_at,
                           latest.latency_ms AS last_latency_ms,
                           latest.error_message AS last_error_message,
                           COALESCE(failures_24h.n, 0) AS failed_24h
                    FROM public.weather_providers wp
                    LEFT JOIN latest
                      ON latest.provider_kind = 'weather'
                     AND latest.provider_code = wp.code
                    LEFT JOIN failures_24h
                      ON failures_24h.provider_kind = 'weather'
                     AND failures_24h.provider_code = wp.code
                    WHERE wp.is_active = TRUE AND wp.deleted_at IS NULL

                    UNION ALL

                    SELECT 'imagery'::text AS provider_kind,
                           ip.code AS provider_code,
                           latest.status AS last_status,
                           latest.probe_at AS last_probe_at,
                           latest.latency_ms AS last_latency_ms,
                           latest.error_message AS last_error_message,
                           COALESCE(failures_24h.n, 0) AS failed_24h
                    FROM public.imagery_providers ip
                    LEFT JOIN latest
                      ON latest.provider_kind = 'imagery'
                     AND latest.provider_code = ip.code
                    LEFT JOIN failures_24h
                      ON failures_24h.provider_kind = 'imagery'
                     AND failures_24h.provider_code = ip.code
                    WHERE ip.is_active = TRUE AND ip.deleted_at IS NULL

                    ORDER BY provider_kind, provider_code
                    """
                )
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def list_tenant_providers(
        self, *, tenant_schema: str
    ) -> list[dict[str, Any]]:
        """Only providers this tenant uses. tenant_schema is set on the session."""
        # Resolve the subset first — public table, but joins look at the
        # tenant's subscription tables which require search_path set.
        # The caller is responsible for that (capability dep sets it).
        rows = (
            await self._pub.execute(
                text(
                    _LATEST_PROBE_CTE
                    + """
                    SELECT 'weather'::text AS provider_kind,
                           wp.code AS provider_code,
                           latest.status AS last_status,
                           latest.probe_at AS last_probe_at,
                           latest.latency_ms AS last_latency_ms,
                           latest.error_message AS last_error_message,
                           COALESCE(failures_24h.n, 0) AS failed_24h
                    FROM public.weather_providers wp
                    LEFT JOIN latest
                      ON latest.provider_kind = 'weather'
                     AND latest.provider_code = wp.code
                    LEFT JOIN failures_24h
                      ON failures_24h.provider_kind = 'weather'
                     AND failures_24h.provider_code = wp.code
                    WHERE wp.is_active = TRUE AND wp.deleted_at IS NULL
                      AND EXISTS (
                        SELECT 1
                        FROM weather_subscriptions ws
                        WHERE ws.provider_code = wp.code
                          AND ws.is_active = TRUE
                          AND ws.deleted_at IS NULL
                      )

                    UNION ALL

                    SELECT 'imagery'::text AS provider_kind,
                           ip.code AS provider_code,
                           latest.status AS last_status,
                           latest.probe_at AS last_probe_at,
                           latest.latency_ms AS last_latency_ms,
                           latest.error_message AS last_error_message,
                           COALESCE(failures_24h.n, 0) AS failed_24h
                    FROM public.imagery_providers ip
                    LEFT JOIN latest
                      ON latest.provider_kind = 'imagery'
                     AND latest.provider_code = ip.code
                    LEFT JOIN failures_24h
                      ON failures_24h.provider_kind = 'imagery'
                     AND failures_24h.provider_code = ip.code
                    WHERE ip.is_active = TRUE AND ip.deleted_at IS NULL
                      AND EXISTS (
                        SELECT 1
                        FROM imagery_aoi_subscriptions ias
                        JOIN public.imagery_products prod
                          ON prod.id = ias.product_id
                        WHERE prod.provider_code = ip.code
                          AND ias.is_active = TRUE
                          AND ias.deleted_at IS NULL
                      )

                    ORDER BY provider_kind, provider_code
                    """
                )
            )
        ).mappings().all()
        # tenant_schema accepted to be explicit about the contract; the
        # actual search_path is set by the caller's auth middleware.
        _ = tenant_schema
        return [dict(r) for r in rows]

    async def cross_tenant_error_histogram(
        self,
        *,
        provider_kind: str,
        provider_code: str,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Aggregate failed-attempt `error_code` counts across every tenant.

        Walks every active tenant schema (same pattern as
        `health_rollup.py`), reads the per-tenant failure table for the
        given provider, sums error_code → count, and merges the result.

        `provider_kind` discriminates which tenant table to read:
          - 'weather'  → tenant_<id>.weather_ingestion_attempts
          - 'imagery'  → tenant_<id>.imagery_ingestion_jobs

        Returns the histogram already sorted by descending count.
        """
        from app.shared.db.session import sanitize_tenant_schema  # local import: no cycle

        if provider_kind not in ("weather", "imagery"):
            return []
        hours = max(1, min(hours, 7 * 24))

        tenants = (
            await self._pub.execute(
                text(
                    """
                    SELECT schema_name
                    FROM public.tenants
                    WHERE status = 'active' AND deleted_at IS NULL
                    """
                )
            )
        ).all()

        merged: dict[str, int] = {}
        for t in tenants:
            try:
                schema = sanitize_tenant_schema(t.schema_name)
            except ValueError:
                continue
            await self._pub.execute(
                text(f"SET LOCAL search_path TO {schema}, public")
            )
            try:
                if provider_kind == "weather":
                    rows = (
                        await self._pub.execute(
                            text(
                                """
                                SELECT COALESCE(error_code, 'uncategorized') AS code,
                                       COUNT(*)::int AS n
                                FROM weather_ingestion_attempts
                                WHERE status = 'failed'
                                  AND provider_code = :p
                                  AND started_at > now() - make_interval(hours => :h)
                                GROUP BY 1
                                """
                            ),
                            {"p": provider_code, "h": hours},
                        )
                    ).all()
                else:
                    # Imagery jobs key on product_id, not provider directly;
                    # join through public.imagery_products.
                    rows = (
                        await self._pub.execute(
                            text(
                                """
                                SELECT COALESCE(ij.error_code, 'uncategorized') AS code,
                                       COUNT(*)::int AS n
                                FROM imagery_ingestion_jobs ij
                                JOIN public.imagery_products ip
                                  ON ip.id = ij.product_id
                                WHERE ij.status = 'failed'
                                  AND ip.provider_code = :p
                                  AND ij.requested_at > now() - make_interval(hours => :h)
                                GROUP BY 1
                                """
                            ),
                            {"p": provider_code, "h": hours},
                        )
                    ).all()
            except Exception:  # noqa: BLE001
                # Tenant mid-migration / missing column — skip, don't fail
                # the whole rollup. Mirrors health_rollup.py behavior.
                continue
            finally:
                await self._pub.execute(text("SET LOCAL search_path TO public"))

            for row in rows:
                merged[row.code] = merged.get(row.code, 0) + int(row.n)

        return [
            {"error_code": code, "count": count}
            for code, count in sorted(
                merged.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

    async def list_recent_probes(
        self, *, provider_kind: str, provider_code: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = (
            await self._pub.execute(
                text(
                    """
                    SELECT probe_at, status, latency_ms, error_message
                    FROM public.provider_probe_results
                    WHERE provider_kind = :kind
                      AND provider_code = :code
                    ORDER BY probe_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "kind": provider_kind,
                    "code": provider_code,
                    "limit": max(1, min(limit, 1000)),
                },
            )
        ).mappings().all()
        return [dict(r) for r in rows]
