"""Request/response shapes for telemetry ingest.

The most important property of `IngestEvent` is what it does **not** have.
`user_id`, `tenant_id`, `actor_role` and `is_platform_staff` are absent from the
model entirely and `extra="ignore"` drops them, so a client physically cannot
express them — they are stamped server-side from `RequestContext`. A tampered
client can pollute its own row and nothing else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# A batch bigger than this is dropped rather than truncated — the SDK flushes at
# 10 and caps its queue at 200, so 50 is generous. Bounded to keep one bad
# client from writing unbounded rows per request.
MAX_EVENTS_PER_BATCH = 50
# Guards the props bag specifically; the whole body is capped by MAX_BODY_BYTES.
MAX_PROPS_KEYS = 20


class IngestEvent(BaseModel):
    """One client event. Identity fields are intentionally not accepted."""

    model_config = ConfigDict(extra="ignore")

    # Client-generated uuid7. The idempotency key for a resent beacon — the
    # server mints one only when it is absent, which makes that event
    # non-idempotent (acceptable; it is the rare case).
    id: UUID | None = None
    # Clamped server-side to now ± 5 min. Clock skew otherwise scatters rows
    # into future chunks where retention and compression will not reach them.
    time: datetime | None = None

    event_name: str = Field(min_length=1, max_length=64)
    feature: str | None = Field(default=None, max_length=64)
    # Route TEMPLATE ("/insights/:farmId"). A resolved path would smuggle ids
    # into a text column and make grouping impossible.
    route: str | None = Field(default=None, max_length=256)
    farm_id: UUID | None = None
    flow: str | None = Field(default=None, max_length=64)
    step: str | None = Field(default=None, max_length=64)

    outcome: str | None = Field(default=None, max_length=16)
    duration_ms: int | None = Field(default=None, ge=0)
    status_code: int | None = Field(default=None, ge=0, le=599)
    error_code: str | None = Field(default=None, max_length=64)

    correlation_id: UUID | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class IngestBatch(BaseModel):
    """One flush from the client SDK."""

    model_config = ConfigDict(extra="ignore")

    session_id: UUID
    app_version: str | None = Field(default=None, max_length=64)
    device_kind: str | None = Field(default=None, max_length=16)
    viewport_w: int | None = Field(default=None, ge=0, le=32767)
    # How many events the client's ring buffer dropped on overflow. Recorded so
    # we know when we are blind rather than idle.
    dropped: int = Field(default=0, ge=0)
    events: list[IngestEvent] = Field(default_factory=list)


class IngestResult(BaseModel):
    """Always returned with 202, even when nothing was stored.

    Telemetry must never break the app, so the status code carries no signal.
    These counts exist for tests and for debugging a client that thinks it is
    reporting when it is not.
    """

    accepted: int = 0
    # Rejected against the closed vocabulary (unknown event/feature/flow/step).
    rejected: int = 0
    # Allow-listed away — the count of props KEYS removed, not events.
    props_dropped: int = 0
    # True when the kill switch is off or the rate limit shed this batch.
    discarded: bool = False
    reason: str | None = None
