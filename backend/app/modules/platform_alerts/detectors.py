"""The five things the sweep looks for, and the SQL behind each.

Read this before adding a sixth. The set was not chosen from a list of
nice-to-haves; each one exists because a real production failure was
invisible to everything else we had on 2026-08-21:

``stream_silent``
    A farm+stream that has stopped producing. The backstop. Catches a
    stream that dies outright, which no failure-row detector can see
    because a dead stream stops writing rows of any kind.

``peer_lag``
    A farm that has not ingested a scene its sibling farms in the same
    tenant already ingested for the same product. This is the sharp one.
    Optical staleness ceilings have to be measured in days to survive the
    satellite revisit gap, so a single stuck farm can hide for most of a
    week underneath them. Its peers are a far tighter reference than the
    calendar: they are on the same tile, on the same day, behind the same
    provider.

``failure_streak``
    N consecutive recorded failures. The only class the pre-existing
    tenant-facing watcher covered.

``stuck_job``
    A job parked in a non-terminal state. Production had one sitting in
    ``running`` for eleven days. It never failed, so nothing counted it.

``task_error``
    A Celery task that raised. Not detected here - it is written by a
    signal handler in ``tasks.py``, because a task that dies before it
    writes its attempt row leaves the sweep nothing to find.

Every detector returns ``Finding`` objects rather than writing. The sweep
owns all writes, so it can collect the keys it saw across every tenant and
auto-resolve what it did not see in a single pass at the end.

Blind-read warning for anyone editing the SQL below: imagery and weather
both have a **block-level** and a **farm-level** subscription path, and a
farm can be cut over from one to the other. Any query that reads only one
path reports a cut-over farm as healthy - it finds no rows and no rows
means no problem. Both paths are UNIONed here on purpose. Thermal in
particular has no block-path rows at all, so a block-only read of thermal
is totally blind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Streams a farm can be silent on, and which severity ceilings apply.
# `index_calc` deliberately rides the optical ceilings: index rows are
# computed from optical scenes, so they cannot be fresher than the imagery
# they come from and a tighter ceiling would just alert on the satellite.
STREAM_WEATHER = "weather"
STREAM_OPTICAL = "imagery_optical"
STREAM_THERMAL = "imagery_thermal"
STREAM_INDEX = "index_calc"

# Stream -> the `category` an alert about it carries. Thermal is its own
# category because an operator triages it separately: different satellite,
# different provider, different revisit.
_STREAM_CATEGORY = {
    STREAM_WEATHER: "weather",
    STREAM_OPTICAL: "imagery",
    STREAM_THERMAL: "thermal",
    STREAM_INDEX: "index_calc",
}

_STREAM_LABEL = {
    STREAM_WEATHER: "Weather",
    STREAM_OPTICAL: "Imagery",
    STREAM_THERMAL: "Thermal",
    STREAM_INDEX: "Index calculation",
}


@dataclass(frozen=True)
class Finding:
    """One detected problem, not yet written anywhere."""

    alert_key: str
    category: str
    kind: str
    severity: str
    title: str
    detail: str | None
    context: dict[str, Any] = field(default_factory=dict)
    farm_id: UUID | None = None
    farm_name: str | None = None


@dataclass(frozen=True)
class Thresholds:
    """The knobs, unpacked from settings once per sweep."""

    weather_warn_hours: int
    weather_crit_hours: int
    optical_warn_hours: int
    optical_crit_hours: int
    thermal_warn_hours: int
    thermal_crit_hours: int
    peer_lag_hours: int
    stuck_job_hours: int
    streak_threshold: int

    def for_stream(self, stream: str) -> tuple[int, int]:
        if stream == STREAM_WEATHER:
            return self.weather_warn_hours, self.weather_crit_hours
        if stream == STREAM_THERMAL:
            return self.thermal_warn_hours, self.thermal_crit_hours
        # Optical and index_calc share a ceiling - see the module note.
        return self.optical_warn_hours, self.optical_crit_hours


def _age_phrase(hours: float) -> str:
    """Plain-words age. Operators scan this column; '3.2 days' reads faster
    than '77 hours', and hours read faster than minutes below a day."""
    if hours < 1:
        return f"{int(hours * 60)} minutes"
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours / 24:.1f} days"


# --- D1: stream_silent -----------------------------------------------------

# One row per (farm, stream) with the newest success on that stream and how
# many active subscriptions feed it. A stream with zero active subscriptions
# is not silent, it is switched off, and must not alert.
#
# The imagery halves UNION the block path and the farm path before taking a
# max, so a farm cut from one to the other keeps a continuous watermark.
_SILENT_SQL = """
WITH thermal_products AS (
    SELECT p.id
      FROM public.imagery_products p
     WHERE EXISTS (
            SELECT 1 FROM unnest(p.bands) AS b(band) WHERE b.band LIKE 'lwir%'
     )
),
img_block AS (
    SELECT b.farm_id,
           (s.product_id IN (SELECT id FROM thermal_products)) AS is_thermal,
           count(*) FILTER (WHERE s.is_active) AS active_subs,
           max(s.last_successful_ingest_at) FILTER (WHERE s.is_active) AS last_ok
      FROM imagery_aoi_subscriptions s
      JOIN blocks b ON b.id = s.block_id AND b.deleted_at IS NULL
     WHERE s.deleted_at IS NULL
     GROUP BY 1, 2
),
img_farm AS (
    SELECT s.farm_id,
           (s.product_id IN (SELECT id FROM thermal_products)) AS is_thermal,
           count(*) FILTER (WHERE s.is_active) AS active_subs,
           max(s.last_successful_ingest_at) FILTER (WHERE s.is_active) AS last_ok
      FROM imagery_farm_subscriptions s
     WHERE s.deleted_at IS NULL
     GROUP BY 1, 2
),
img AS (
    SELECT farm_id,
           CASE WHEN is_thermal THEN 'imagery_thermal' ELSE 'imagery_optical' END AS stream,
           sum(active_subs) AS active_subs,
           max(last_ok) AS last_ok
      FROM (SELECT * FROM img_block UNION ALL SELECT * FROM img_farm) u
     GROUP BY 1, 2
),
wx_block AS (
    SELECT b.farm_id,
           count(*) FILTER (WHERE s.is_active) AS active_subs,
           max(s.last_successful_ingest_at) FILTER (WHERE s.is_active) AS last_ok
      FROM weather_subscriptions s
      JOIN blocks b ON b.id = s.block_id AND b.deleted_at IS NULL
     WHERE s.deleted_at IS NULL
     GROUP BY 1
),
wx_farm AS (
    SELECT s.farm_id,
           count(*) FILTER (WHERE s.is_active) AS active_subs,
           max(s.last_successful_ingest_at) FILTER (WHERE s.is_active) AS last_ok
      FROM weather_farm_subscriptions s
     WHERE s.deleted_at IS NULL
     GROUP BY 1
),
wx AS (
    SELECT farm_id, 'weather' AS stream,
           sum(active_subs) AS active_subs, max(last_ok) AS last_ok
      FROM (SELECT * FROM wx_block UNION ALL SELECT * FROM wx_farm) u
     GROUP BY 1
),
-- Index freshness is measured on the rows the calculation actually
-- produces, not on `indices_calc_runs`. The lineage table is best-effort
-- and has been silently empty before; keying an alert on it would report
-- every farm as broken the moment lineage writing regresses.
idx AS (
    SELECT b.farm_id, 'index_calc' AS stream,
           NULL::bigint AS active_subs,
           max(a.inserted_at) AS last_ok
      FROM block_index_aggregates a
      JOIN blocks b ON b.id = a.block_id AND b.deleted_at IS NULL
     WHERE a.inserted_at > now() - interval '120 days'
     GROUP BY 1
),
streams AS (
    SELECT * FROM img
    UNION ALL SELECT * FROM wx
    UNION ALL SELECT farm_id, stream, active_subs, last_ok FROM idx
)
SELECT f.id AS farm_id,
       f.name AS farm_name,
       s.stream,
       s.active_subs,
       s.last_ok,
       EXTRACT(epoch FROM (now() - s.last_ok)) / 3600.0 AS age_hours
  FROM streams s
  JOIN farms f ON f.id = s.farm_id AND f.deleted_at IS NULL
"""


async def detect_stream_silent(
    session: AsyncSession, *, tenant_key: str, th: Thresholds
) -> list[Finding]:
    rows = (await session.execute(text(_SILENT_SQL))).mappings().all()
    out: list[Finding] = []
    for r in rows:
        stream = r["stream"]
        # index_calc has no subscriptions of its own; every other stream
        # must have at least one active feed before silence means anything.
        if stream != STREAM_INDEX and not (r["active_subs"] or 0):
            continue
        warn_h, crit_h = th.for_stream(stream)

        if r["last_ok"] is None:
            # Never succeeded. Real, but it is a provisioning problem rather
            # than a regression, so it opens at warning and says so.
            age_hours = None
            severity = "warning"
            detail = (
                f"{_STREAM_LABEL[stream]} has never completed successfully for this farm. "
                f"Check that the subscription was provisioned."
            )
        else:
            age_hours = float(r["age_hours"])
            if age_hours >= crit_h:
                severity = "critical"
            elif age_hours >= warn_h:
                severity = "warning"
            else:
                continue
            detail = (
                f"Last successful {_STREAM_LABEL[stream].lower()} was "
                f"{_age_phrase(age_hours)} ago. "
                f"The alerting ceiling for this stream is {warn_h}h "
                f"(warning) / {crit_h}h (critical)."
            )

        out.append(
            Finding(
                alert_key=f"stream_silent:{tenant_key}:{r['farm_id']}:{stream}",
                category=_STREAM_CATEGORY[stream],
                kind="stream_silent",
                severity=severity,
                title=f"{_STREAM_LABEL[stream]} silent on {r['farm_name']}",
                detail=detail,
                context={
                    "stream": stream,
                    "last_success_at": r["last_ok"].isoformat() if r["last_ok"] else None,
                    "age_hours": round(age_hours, 2) if age_hours is not None else None,
                    "warn_hours": warn_h,
                    "critical_hours": crit_h,
                    "active_subscriptions": int(r["active_subs"] or 0),
                },
                farm_id=r["farm_id"],
                farm_name=r["farm_name"],
            )
        )
    return out


# --- D2: peer_lag ----------------------------------------------------------

# For each product, find the newest scene day any farm in this tenant has
# ingested and when that ingest happened. Then list active farms on the same
# product that have nothing for that scene day.
#
# Why this beats a clock: two farms on the same Sentinel-2 tile can sit up to
# a full day apart purely because discovery runs on a 24h cadence whose phase
# is whatever time of day the subscription last ran. That offset is not a
# fault. Past `peer_lag_hours` it is no longer explainable by the cadence,
# and the peer that already has the scene proves the provider had it.
_PEER_SQL = """
WITH thermal_products AS (
    SELECT p.id
      FROM public.imagery_products p
     WHERE EXISTS (
            SELECT 1 FROM unnest(p.bands) AS b(band) WHERE b.band LIKE 'lwir%'
     )
),
-- Every farm with a live feed for a product, over BOTH subscription paths.
active_farm_product AS (
    SELECT DISTINCT b.farm_id, s.product_id
      FROM imagery_aoi_subscriptions s
      JOIN blocks b ON b.id = s.block_id AND b.deleted_at IS NULL
     WHERE s.deleted_at IS NULL AND s.is_active
    UNION
    SELECT DISTINCT s.farm_id, s.product_id
      FROM imagery_farm_subscriptions s
     WHERE s.deleted_at IS NULL AND s.is_active
),
-- Scene days a farm actually holds, over BOTH job paths.
farm_scene AS (
    SELECT b.farm_id, j.product_id, j.scene_datetime::date AS scene_day,
           max(j.completed_at) AS ingested_at
      FROM imagery_ingestion_jobs j
      JOIN blocks b ON b.id = j.block_id AND b.deleted_at IS NULL
     WHERE j.status = 'succeeded'
       AND j.scene_datetime > now() - interval '30 days'
     GROUP BY 1, 2, 3
    UNION ALL
    SELECT j.farm_id, j.product_id, j.scene_datetime::date AS scene_day,
           max(j.completed_at) AS ingested_at
      FROM imagery_farm_ingestion_jobs j
     WHERE j.status = 'succeeded'
       AND j.scene_datetime > now() - interval '30 days'
     GROUP BY 1, 2, 3
),
-- The reference: newest scene day seen anywhere in the tenant per product.
newest AS (
    SELECT DISTINCT ON (product_id)
           product_id, scene_day, max(ingested_at) AS peer_ingested_at
      FROM farm_scene
     GROUP BY product_id, scene_day
     ORDER BY product_id, scene_day DESC
)
SELECT f.id AS farm_id,
       f.name AS farm_name,
       n.product_id,
       p.code AS product_code,
       (n.product_id IN (SELECT id FROM thermal_products)) AS is_thermal,
       n.scene_day,
       n.peer_ingested_at,
       EXTRACT(epoch FROM (now() - n.peer_ingested_at)) / 3600.0 AS lag_hours,
       (SELECT count(DISTINCT fs.farm_id)
          FROM farm_scene fs
         WHERE fs.product_id = n.product_id AND fs.scene_day = n.scene_day) AS peer_farms
  FROM newest n
  JOIN active_farm_product afp ON afp.product_id = n.product_id
  JOIN farms f ON f.id = afp.farm_id AND f.deleted_at IS NULL
  LEFT JOIN public.imagery_products p ON p.id = n.product_id
 WHERE NOT EXISTS (
        SELECT 1 FROM farm_scene fs
         WHERE fs.farm_id = afp.farm_id
           AND fs.product_id = n.product_id
           AND fs.scene_day = n.scene_day
 )
   AND n.peer_ingested_at < now() - make_interval(hours => :peer_lag_hours)
"""


async def detect_peer_lag(
    session: AsyncSession, *, tenant_key: str, th: Thresholds
) -> list[Finding]:
    rows = (
        (await session.execute(text(_PEER_SQL), {"peer_lag_hours": th.peer_lag_hours}))
        .mappings()
        .all()
    )
    out: list[Finding] = []
    for r in rows:
        stream = STREAM_THERMAL if r["is_thermal"] else STREAM_OPTICAL
        lag_hours = float(r["lag_hours"])
        # Two cadence periods behind its peers is no longer a phase offset.
        severity = "critical" if lag_hours >= th.peer_lag_hours * 2 else "warning"
        out.append(
            Finding(
                alert_key=f"peer_lag:{tenant_key}:{r['farm_id']}:{r['product_id']}",
                category=_STREAM_CATEGORY[stream],
                kind="peer_lag",
                severity=severity,
                title=f"{r['farm_name']} is behind other farms on {r['product_code']}",
                detail=(
                    f"Scene day {r['scene_day']} was ingested for "
                    f"{r['peer_farms']} other farm(s) in this tenant "
                    f"{_age_phrase(lag_hours)} ago, and this farm still has "
                    f"nothing for it. The provider had the scene, so this is "
                    f"not a satellite gap."
                ),
                context={
                    "product_code": r["product_code"],
                    "scene_day": str(r["scene_day"]),
                    "peer_ingested_at": (
                        r["peer_ingested_at"].isoformat() if r["peer_ingested_at"] else None
                    ),
                    "lag_hours": round(lag_hours, 2),
                    "peer_farms": int(r["peer_farms"] or 0),
                    "peer_lag_threshold_hours": th.peer_lag_hours,
                },
                farm_id=r["farm_id"],
                farm_name=r["farm_name"],
            )
        )
    return out


# --- D3: failure_streak ----------------------------------------------------

# Recorded failures, read from the per-tenant health view so the streak
# counting stays in one place. The view already spans weather and both
# imagery job paths.
_STREAK_SQL = """
WITH ranked AS (
    SELECT kind, subscription_id, block_id, farm_id, provider_code,
           started_at, failed_streak_position, error_code, error_message,
           ROW_NUMBER() OVER (
               PARTITION BY kind, subscription_id ORDER BY started_at DESC
           ) AS rn
      FROM v_integration_recent_attempts
)
SELECT r.kind, r.subscription_id, r.farm_id, r.provider_code,
       r.failed_streak_position, r.error_code, r.error_message, r.started_at,
       f.name AS farm_name
  FROM ranked r
  LEFT JOIN farms f ON f.id = r.farm_id
 WHERE r.rn = 1
   AND r.failed_streak_position >= :threshold
"""

# Index calculations that ran and failed. Separate from the view because
# index calc is not an "integration attempt" - it is what happens after one.
_CALC_FAIL_SQL = """
SELECT b.farm_id,
       f.name AS farm_name,
       count(*) AS failures,
       max(c.completed_at) AS last_failed_at,
       (array_agg(c.error ORDER BY c.completed_at DESC))[1] AS last_error
  FROM indices_calc_runs c
  JOIN blocks b ON b.id = c.block_id
  LEFT JOIN farms f ON f.id = b.farm_id
 WHERE c.outcome = 'failed'
   AND c.completed_at > now() - interval '24 hours'
 GROUP BY 1, 2
"""


async def detect_failure_streaks(
    session: AsyncSession, *, tenant_key: str, th: Thresholds
) -> list[Finding]:
    out: list[Finding] = []

    # The health view arrived in tenant migration 0078. A tenant created
    # before it, or mid-migration, simply has no view - skip rather than
    # fail the whole tenant's sweep.
    has_view = (
        await session.execute(text("SELECT to_regclass('v_integration_recent_attempts')"))
    ).scalar()
    if has_view:
        rows = (
            (await session.execute(text(_STREAK_SQL), {"threshold": th.streak_threshold}))
            .mappings()
            .all()
        )
        for r in rows:
            streak = int(r["failed_streak_position"])
            severity = "critical" if streak >= th.streak_threshold * 2 else "warning"
            category = "weather" if r["kind"] == "weather" else "imagery"
            out.append(
                Finding(
                    alert_key=f"failure_streak:{tenant_key}:{r['kind']}:{r['subscription_id']}",
                    category=category,
                    kind="failure_streak",
                    severity=severity,
                    title=(
                        f"{r['kind'].title()} failing on "
                        f"{r['farm_name'] or 'unknown farm'}"
                        + (f" ({r['provider_code']})" if r["provider_code"] else "")
                    ),
                    detail=(
                        f"{streak} consecutive failed attempts. "
                        f"Last error: {r['error_code'] or 'unknown'}"
                        + (f" - {str(r['error_message'])[:200]}" if r["error_message"] else "")
                    ),
                    context={
                        "subscription_id": str(r["subscription_id"]),
                        "streak_length": streak,
                        "provider_code": r["provider_code"],
                        "error_code": r["error_code"],
                        "last_attempt_at": r["started_at"].isoformat() if r["started_at"] else None,
                    },
                    farm_id=r["farm_id"],
                    farm_name=r["farm_name"],
                )
            )

    has_calc = (await session.execute(text("SELECT to_regclass('indices_calc_runs')"))).scalar()
    if has_calc:
        rows = (await session.execute(text(_CALC_FAIL_SQL))).mappings().all()
        for r in rows:
            failures = int(r["failures"])
            out.append(
                Finding(
                    alert_key=f"failure_streak:{tenant_key}:index_calc:{r['farm_id']}",
                    category="index_calc",
                    kind="failure_streak",
                    severity="critical" if failures >= th.streak_threshold else "warning",
                    title=f"Index calculation failing on {r['farm_name'] or 'unknown farm'}",
                    detail=(
                        f"{failures} index calculation run(s) failed in the last 24 hours. "
                        f"Last error: {str(r['last_error'] or 'unknown')[:200]}"
                    ),
                    context={
                        "failures_24h": failures,
                        "last_failed_at": (
                            r["last_failed_at"].isoformat() if r["last_failed_at"] else None
                        ),
                        "last_error": str(r["last_error"])[:500] if r["last_error"] else None,
                    },
                    farm_id=r["farm_id"],
                    farm_name=r["farm_name"],
                )
            )
    return out


# --- D5: stuck_job ---------------------------------------------------------

# Non-terminal jobs older than the ceiling, over both job paths. Grouped per
# farm: forty stuck blocks on one farm is one problem to go and look at, not
# forty alerts.
_STUCK_SQL = """
WITH stuck AS (
    SELECT b.farm_id, j.id AS job_id, j.status, j.requested_at
      FROM imagery_ingestion_jobs j
      JOIN blocks b ON b.id = j.block_id AND b.deleted_at IS NULL
     WHERE j.status IN ('pending', 'requested', 'running')
       AND j.requested_at < now() - make_interval(hours => :stuck_hours)
       AND j.requested_at > now() - interval '60 days'
    UNION ALL
    SELECT j.farm_id, j.id AS job_id, j.status, j.requested_at
      FROM imagery_farm_ingestion_jobs j
     WHERE j.status IN ('pending', 'requested', 'running')
       AND j.requested_at < now() - make_interval(hours => :stuck_hours)
       AND j.requested_at > now() - interval '60 days'
)
SELECT s.farm_id,
       f.name AS farm_name,
       count(*) AS stuck_jobs,
       min(s.requested_at) AS oldest_requested_at,
       EXTRACT(epoch FROM (now() - min(s.requested_at))) / 3600.0 AS oldest_age_hours
  FROM stuck s
  LEFT JOIN farms f ON f.id = s.farm_id
 GROUP BY 1, 2
"""


async def detect_stuck_jobs(
    session: AsyncSession, *, tenant_key: str, th: Thresholds
) -> list[Finding]:
    rows = (
        (await session.execute(text(_STUCK_SQL), {"stuck_hours": th.stuck_job_hours}))
        .mappings()
        .all()
    )
    out: list[Finding] = []
    for r in rows:
        age = float(r["oldest_age_hours"])
        # A day parked is not a slow queue any more.
        severity = "critical" if age >= 24 else "warning"
        out.append(
            Finding(
                alert_key=f"stuck_job:{tenant_key}:{r['farm_id']}",
                category="imagery",
                kind="stuck_job",
                severity=severity,
                title=f"Imagery jobs stuck on {r['farm_name'] or 'unknown farm'}",
                detail=(
                    f"{r['stuck_jobs']} job(s) have been in a non-terminal state for "
                    f"more than {th.stuck_job_hours}h. The oldest was requested "
                    f"{_age_phrase(age)} ago. A job that never finishes also never "
                    f"fails, so nothing else reports these."
                ),
                context={
                    "stuck_jobs": int(r["stuck_jobs"]),
                    "oldest_requested_at": (
                        r["oldest_requested_at"].isoformat() if r["oldest_requested_at"] else None
                    ),
                    "oldest_age_hours": round(age, 2),
                    "stuck_threshold_hours": th.stuck_job_hours,
                },
                farm_id=r["farm_id"],
                farm_name=r["farm_name"],
            )
        )
    return out


# Kinds the sweep recomputes in full every run, and may therefore
# auto-resolve by absence. `task_error` is excluded - see the repository.
SWEEP_KINDS = ["stream_silent", "peer_lag", "failure_streak", "stuck_job"]

DETECTORS = (
    detect_stream_silent,
    detect_peer_lag,
    detect_failure_streaks,
    detect_stuck_jobs,
)
