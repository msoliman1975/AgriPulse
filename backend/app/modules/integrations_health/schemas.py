"""Integration health response schemas — read-only views of weather/imagery
sync state per Farm and per Block.

The view bodies live in tenant migrations 0019 + 0022; these schemas
mirror the shape and are used by both the routers and the queries hook
on the frontend (via OpenAPI/typed clients later)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FarmIntegrationHealthResponse(BaseModel):
    """One row from `tenant_<id>.v_farm_integration_health`."""

    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    weather_active_subs: int
    weather_last_sync_at: datetime | None
    weather_last_failed_at: datetime | None
    imagery_active_subs: int
    imagery_last_sync_at: datetime | None
    imagery_failed_24h: int
    # PR-IH2 additions
    weather_failed_24h: int = 0
    weather_running_count: int = 0
    imagery_running_count: int = 0
    weather_overdue_count: int = 0
    imagery_overdue_count: int = 0


class BlockIntegrationHealthResponse(BaseModel):
    """One row from `tenant_<id>.v_block_integration_health`."""

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    farm_id: UUID
    block_name: str
    weather_active_subs: int
    weather_last_sync_at: datetime | None
    weather_last_failed_at: datetime | None
    imagery_active_subs: int
    imagery_last_sync_at: datetime | None
    imagery_failed_24h: int
    # PR-IH2 additions
    weather_failed_24h: int = 0
    weather_running_count: int = 0
    imagery_running_count: int = 0
    weather_overdue_count: int = 0
    imagery_overdue_count: int = 0


class QueueEntry(BaseModel):
    """One row in the pipeline/queue view (PR-IH4).

    Unified shape across weather + imagery. `state` is one of:
      - 'overdue'  : subscription's cadence has elapsed since
                     last_successful_ingest_at
      - 'running'  : weather attempt with status='running', or
                     imagery job with status in ('pending', 'requested',
                     'running')
      - 'stuck'    : 'running' for longer than the stuck threshold
                     (default 30 minutes; configurable per deploy).
    """

    model_config = ConfigDict(from_attributes=True)

    kind: str  # 'weather' | 'imagery'
    state: str  # 'overdue' | 'running' | 'stuck'
    subscription_id: UUID
    block_id: UUID
    farm_id: UUID | None
    provider_code: str | None
    # For overdue: last_successful_ingest_at (may be null on never-synced).
    # For running/stuck: the attempt/job's started_at.
    since: datetime | None
    # Stuck rows carry the offending attempt id; overdue/running rows can
    # too if they're attached to a specific attempt.
    attempt_id: UUID | None = None


class ProviderHealthRow(BaseModel):
    """One row in the Providers tab (PR-IH6).

    Aggregates the most recent probe per provider plus a 24h failure
    count. `last_probe_at` is null if the scheduler hasn't run yet —
    the UI maps that to a "pending" pill.
    """

    model_config = ConfigDict(from_attributes=True)

    provider_kind: str  # 'weather' | 'imagery'
    provider_code: str
    last_status: str | None  # 'ok' | 'error' | 'timeout' | None
    last_probe_at: datetime | None
    last_latency_ms: int | None
    last_error_message: str | None
    failed_24h: int


class ProviderErrorHistogramEntry(BaseModel):
    """One bucket in the per-provider failure-cause histogram (PR-IH10)."""

    model_config = ConfigDict(from_attributes=True)

    error_code: str  # 'tls_trust' | 'timeout' | … | 'uncategorized'
    count: int


class ProviderProbeRow(BaseModel):
    """One row in the per-provider probe-history drill-down."""

    model_config = ConfigDict(from_attributes=True)

    probe_at: datetime
    status: str
    latency_ms: int | None
    error_message: str | None


class IntegrationAttemptRow(BaseModel):
    """One row from `tenant_<id>.v_integration_recent_attempts`.

    Unified shape across weather + imagery. `scene_id` is imagery-only;
    `rows_ingested` is weather-only. Both are nullable.

    PR-IH8: added explicit `queued_at`, `wait_ms`, `run_ms` so the Runs
    tab can distinguish "stuck in queue" from "running forever".
    `duration_ms` is retained for older clients and equals `run_ms`.
    """

    model_config = ConfigDict(from_attributes=True)

    attempt_id: UUID
    kind: str  # 'weather' | 'imagery'
    subscription_id: UUID
    block_id: UUID
    farm_id: UUID | None
    provider_code: str | None
    started_at: datetime
    queued_at: datetime | None = None
    completed_at: datetime | None
    status: str  # 'running' | 'succeeded' | 'failed' | 'skipped'
    duration_ms: int | None
    wait_ms: int | None = None
    run_ms: int | None = None
    rows_ingested: int | None
    error_code: str | None
    error_message: str | None
    scene_id: str | None
    # PR-IH9: Nth consecutive failure for this subscription, inclusive.
    # 0 for non-failures or first-attempt successes. UI shows
    # "Attempt #N" badge when > 1.
    failed_streak_position: int = 0
