"""Response shapes for the usage dashboard (TEL-6/TEL-7).

Separate from `schemas.py`, which is the ingest contract. The two have opposite
trust models — ingest distrusts everything the client sends, these are things
only the server can know — and keeping them in one file invites a reader to
assume a field on one is available on the other.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UsageFilters(BaseModel):
    """Echoed back so a chart can label itself without re-deriving the query."""

    start: date
    end: date
    tenant_id: UUID | None = None
    include_staff: bool = False


class EngagementKpis(BaseModel):
    dau: int = 0
    wau: int = 0
    mau: int = 0
    #: DAU ÷ WAU. "Of the people who used it this week, what share used it
    #: today." Computed server-side so every surface reads the same number.
    stickiness: float = 0.0
    median_session_seconds: float = 0.0
    sessions: int = 0
    sessions_per_user: float = 0.0


class DailyPoint(BaseModel):
    day: date
    events: int = 0
    users: int = 0


class RouteDwell(BaseModel):
    route: str
    total_ms: int = 0
    visits: int = 0
    #: Median, not mean. The mean is dominated by the long tail of tabs left
    #: open, even after the 30-minute cap the client applies.
    median_ms: int = 0


class FeatureAdoption(BaseModel):
    feature: str
    events: int = 0
    users: int = 0
    tenants: int = 0
    last_used: date | None = None


class FlowFunnel(BaseModel):
    flow: str
    entries: int = 0
    completions: int = 0
    abandoned: int = 0
    #: The step most abandoning sessions reached last. None means they left
    #: before any step — they bounced at entry, which is its own answer.
    died_at: str | None = None


class FlowStep(BaseModel):
    flow: str
    step: str
    sessions: int = 0


class ErrorDenseRoute(BaseModel):
    route: str
    views: int = 0
    errors: int = 0
    error_rate: float = 0.0


class RecentError(BaseModel):
    time: datetime
    route: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    #: Joins straight to the server log line and the trace.
    correlation_id: UUID | None = None
    method: str | None = None


class RetryStorm(BaseModel):
    feature: str | None = None
    action: str | None = None
    storms: int = 0
    users: int = 0


class SlowAction(BaseModel):
    feature: str
    p95_ms: int = 0
    samples: int = 0


class TenantHealth(BaseModel):
    tenant_id: UUID
    last_seen: date | None = None
    wau: int = 0
    #: Breadth of use. Two capabilities is a different retention risk from
    #: twelve, at the same event count.
    features_used: int = 0
    events: int = 0


class UsageOverview(BaseModel):
    """One request, one page. The dashboard needs all of this at once, and
    seven round trips would each re-scan the same window."""

    filters: UsageFilters
    kpis: EngagementKpis
    daily: list[DailyPoint] = Field(default_factory=list)
    routes: list[RouteDwell] = Field(default_factory=list)
    features: list[FeatureAdoption] = Field(default_factory=list)
    #: Capabilities with zero use in the window — the "should we delete this?"
    #: list. Comes from the taxonomy, not the data: a feature nobody ever used
    #: produces no rows to find.
    cold_features: list[str] = Field(default_factory=list)
    funnels: list[FlowFunnel] = Field(default_factory=list)
    funnel_steps: list[FlowStep] = Field(default_factory=list)
    error_routes: list[ErrorDenseRoute] = Field(default_factory=list)
    recent_errors: list[RecentError] = Field(default_factory=list)
    retry_storms: list[RetryStorm] = Field(default_factory=list)
    slow_actions: list[SlowAction] = Field(default_factory=list)
    tenants: list[TenantHealth] = Field(default_factory=list)
