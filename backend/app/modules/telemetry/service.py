"""Telemetry ingest: validate against the closed vocabulary, stamp identity, write.

Two invariants this module exists to hold:

1. **The client never asserts identity.** `user_id` / `tenant_id` / `actor_role` /
   `is_platform_staff` / `locale` come from the validated JWT via
   `RequestContext`, never from the payload. `IngestEvent` cannot even express
   them.
2. **Telemetry never breaks the app.** Every failure path here returns a result
   instead of raising, and the router answers 202 regardless.
"""

from __future__ import annotations

import time as _time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.telemetry.schemas import (
    MAX_EVENTS_PER_BATCH,
    MAX_PROPS_KEYS,
    IngestBatch,
    IngestEvent,
    IngestResult,
)
from app.modules.telemetry.taxonomy import Taxonomy, get_taxonomy
from app.shared.auth.context import RequestContext
from app.shared.db.ids import uuid7

# Client clocks are not trustworthy. Anything outside this window is replaced
# with server now() rather than dropped — the event is still real, only its
# timestamp is wrong.
_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)

# 60 batches/min/session. The SDK flushes every 15s plus on route change, so a
# busy session lands well under this; anything above is a loop or an attack.
_RATE_LIMIT_BATCHES = 60
_RATE_LIMIT_WINDOW_SECONDS = 60.0
# Bound the bookkeeping itself, or a long-lived process leaks one deque per
# session id ever seen.
_RATE_LIMIT_MAX_SESSIONS = 10_000


_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, schema_version,
        session_id, user_id, tenant_id, actor_role, is_platform_staff,
        event_name, feature, route, farm_id, flow, step,
        outcome, duration_ms, status_code, error_code,
        correlation_id, locale, app_version, device_kind, viewport_w,
        props
    ) VALUES (
        :time, :id, :schema_version,
        :session_id, :user_id, :tenant_id, :actor_role, :is_platform_staff,
        :event_name, :feature, :route, :farm_id, :flow, :step,
        :outcome, :duration_ms, :status_code, :error_code,
        :correlation_id, :locale, :app_version, :device_kind, :viewport_w,
        CAST(:props AS jsonb)
    )
    ON CONFLICT (time, id) DO NOTHING
    """
)
# `props` is bound as a JSON string with an explicit CAST — the correct wire form
# for jsonb. Every other bind is a real datetime / UUID / int object. Passing
# `.isoformat()` strings through a CAST is the #331 / #332 / #335 bug family;
# do not "simplify" these binds into strings.


class TelemetryService(Protocol):
    async def ingest(
        self, *, session: AsyncSession, context: RequestContext, batch: IngestBatch
    ) -> IngestResult: ...


@dataclass
class _RateLimiter:
    """In-process sliding window per session. Deliberately not Redis-backed.

    A single API replica is the deployment today, and the cost of a miss is a
    few extra rows — not worth a network hop on the hot path.
    """

    _hits: dict[UUID, deque[float]]

    @classmethod
    def create(cls) -> _RateLimiter:
        return cls(_hits={})

    def allow(self, session_id: UUID) -> bool:
        now = _time.monotonic()
        window = self._hits.get(session_id)
        if window is None:
            if len(self._hits) >= _RATE_LIMIT_MAX_SESSIONS:
                self._evict(now)
            window = self._hits.setdefault(session_id, deque())
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= _RATE_LIMIT_BATCHES:
            return False
        window.append(now)
        return True

    def _evict(self, now: float) -> None:
        """Drop sessions with nothing inside the window."""
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        stale = [sid for sid, w in self._hits.items() if not w or w[-1] < cutoff]
        for sid in stale:
            del self._hits[sid]
        if not stale:
            # Every session is active — clear the oldest half rather than grow
            # without bound. Losing rate-limit state fails open, which is the
            # right direction for telemetry.
            for sid in list(self._hits)[: len(self._hits) // 2]:
                del self._hits[sid]


class TelemetryServiceImpl:
    def __init__(self, taxonomy: Taxonomy | None = None) -> None:
        self._log = get_logger(__name__)
        self._taxonomy = taxonomy
        self._limiter = _RateLimiter.create()

    @property
    def taxonomy(self) -> Taxonomy:
        return self._taxonomy or get_taxonomy()

    async def ingest(
        self, *, session: AsyncSession, context: RequestContext, batch: IngestBatch
    ) -> IngestResult:
        if not self._limiter.allow(batch.session_id):
            self._log.info("telemetry_rate_limited", session_id=str(batch.session_id))
            return IngestResult(discarded=True, reason="rate_limited")

        events = batch.events[:MAX_EVENTS_PER_BATCH]
        oversize = len(batch.events) - len(events)

        rows: list[dict[str, Any]] = []
        rejected = oversize
        props_dropped = 0
        now = datetime.now(UTC)
        taxonomy = self.taxonomy

        for event in events:
            row = self._build_row(event, batch=batch, context=context, now=now, taxonomy=taxonomy)
            if row is None:
                rejected += 1
                continue
            props_dropped += int(row.pop("_props_dropped"))
            rows.append(row)

        if rows:
            await session.execute(_INSERT, rows)
            await session.commit()

        if rejected or batch.dropped or props_dropped:
            # Logged, not silent: a client reporting nothing looks identical to
            # an idle user unless we say so somewhere.
            self._log.info(
                "telemetry_ingest_lossy",
                accepted=len(rows),
                rejected=rejected,
                props_dropped=props_dropped,
                client_dropped=batch.dropped,
                session_id=str(batch.session_id),
            )

        return IngestResult(accepted=len(rows), rejected=rejected, props_dropped=props_dropped)

    def _build_row(
        self,
        event: IngestEvent,
        *,
        batch: IngestBatch,
        context: RequestContext,
        now: datetime,
        taxonomy: Taxonomy,
    ) -> dict[str, Any] | None:
        """One bind-parameter set, or None when the vocabulary rejects it.

        A rejected event is dropped on its own — never the batch. A stale client
        emitting one retired event name must not lose the other 49.
        """
        if not taxonomy.has_event(event.event_name):
            return None
        if event.feature is not None and not taxonomy.has_feature(event.feature):
            return None
        if event.flow is not None and not taxonomy.has_flow(event.flow):
            return None
        # A step is meaningless without its flow, and must belong to it.
        if event.step is not None and (
            event.flow is None or not taxonomy.allows_step(event.flow, event.step)
        ):
            return None
        if len(event.props) > MAX_PROPS_KEYS:
            return None

        kept_props, dropped = taxonomy.filter_props(event.event_name, event.props)

        # --- identity: server-stamped, payload ignored ----------------------
        actor_role = _actor_role(context)
        is_platform_staff = context.platform_role is not None

        return {
            "time": _clamp_time(event.time, now),
            "id": event.id or uuid7(),
            "schema_version": taxonomy.version,
            "session_id": batch.session_id,
            "user_id": context.user_id,
            "tenant_id": context.tenant_id,
            "actor_role": actor_role,
            "is_platform_staff": is_platform_staff,
            "event_name": event.event_name,
            "feature": event.feature,
            "route": event.route,
            "farm_id": event.farm_id,
            "flow": event.flow,
            "step": event.step,
            "outcome": event.outcome,
            "duration_ms": event.duration_ms,
            "status_code": event.status_code,
            "error_code": event.error_code,
            "correlation_id": event.correlation_id,
            "locale": context.preferred_language,
            "app_version": batch.app_version,
            "device_kind": batch.device_kind,
            "viewport_w": batch.viewport_w,
            "props": _json_dumps(kept_props),
            "_props_dropped": dropped,
        }


def _clamp_time(when: datetime | None, now: datetime) -> datetime:
    """Replace an implausible client timestamp with a server-derived one.

    Future-dated rows are the dangerous case: they land in chunks that
    compression and retention policies will not reach for months.

    The fallback is floored to the whole minute, and that detail matters more
    than it looks. `(time, id)` is the ON CONFLICT target that makes a resent
    beacon a no-op — so if the fallback were a raw `now()`, two deliveries of the
    *same* event would land on different timestamps and both insert. Idempotency
    would silently hold for well-behaved clocks and silently fail for skewed
    ones, which is the worst possible split.

    Flooring makes the fallback stable for a whole minute, so a resend (which
    happens within seconds, on an unload/visibilitychange race) collapses
    correctly. The cost is sub-minute precision on timestamps we had already
    judged untrustworthy — nothing of value is lost. A resend straddling a
    minute boundary can still double-count; that window is small and accepted.

    Dropping these events instead was the alternative and is worse: a single
    misconfigured machine would disappear from analytics entirely, which is both
    more likely and more damaging than a rare duplicate.
    """
    if when is None:
        return now.replace(second=0, microsecond=0)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if abs(when - now) > _CLOCK_SKEW_TOLERANCE:
        return now.replace(second=0, microsecond=0)
    return when


def _actor_role(context: RequestContext) -> str | None:
    """The most specific role we can name for this actor.

    Platform role wins (platform staff are the cohort we exclude), then tenant
    role. Farm-scoped roles are deliberately not resolved here: an event is not
    always about a farm, and picking one of several farm scopes would be
    arbitrary.
    """
    if context.platform_role is not None:
        return str(context.platform_role)
    if context.tenant_role is not None:
        return str(context.tenant_role)
    if context.farm_scopes:
        roles = {str(s.role) for s in context.farm_scopes}
        if len(roles) == 1:
            return roles.pop()
    return None


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), default=str)


_default: TelemetryService | None = None


def get_telemetry_service() -> TelemetryService:
    global _default
    if _default is None:
        _default = TelemetryServiceImpl()
    return _default


def set_telemetry_service(impl: TelemetryService | None) -> None:
    """Test seam; also resets the rate limiter between tests."""
    global _default
    _default = impl
