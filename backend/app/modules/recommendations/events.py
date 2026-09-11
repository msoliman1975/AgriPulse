"""Public event types for the recommendations module. Versioned per
ARCHITECTURE.md § 6.1 — bumping the suffix is a breaking schema change
for subscribers.

The notifications module subscribes to ``RecommendationOpenedV1`` and
fans out across in_app / email / webhook channels, mirroring the alert
fan-out. The same payload-carries-content trade-off applies: a sync
subscriber on a separate connection cannot read the not-yet-committed
recommendations row, so the renderable fields ride on the event itself.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class RecommendationOpenedV1(Event):
    event_name: ClassVar[str] = "recommendations.recommendation_opened.v1"

    recommendation_id: UUID
    block_id: UUID
    # Sub-block grid cell for cell-scoped recs (per-cell P2); None = block.
    cell_id: UUID | None = None
    farm_id: UUID
    tree_id: UUID
    tree_code: str
    tree_version: int
    action_type: str
    severity: str
    confidence: Decimal
    created_at: datetime
    # Tenant context — added so cross-module subscribers (notifications)
    # can scope DB writes without walking every tenant.
    tenant_schema: str | None = None
    # Content snapshot. Carried on the event so a sync subscriber on a
    # separate connection can render templates without reading the
    # uncommitted recommendations row.
    text_en: str | None = None
    text_ar: str | None = None
    parameters: dict[str, Any] | None = None
    evaluation_snapshot: dict[str, Any] | None = None
    # Per-cell P2 digest: a cell-scoped tree opens one rec per grid cell, which
    # would flood notifications. The sweep suppresses the per-cell events for
    # notifications (they still drive the map / recs page) and publishes ONE
    # synthetic block-level RecommendationOpenedV1 (cell_id=None) whose text_en/
    # text_ar summarise "N zones flagged"; ``zone_count`` marks it as a digest.
    zone_count: int | None = None
    # The evaluation run that opened this recommendation, when one was
    # open. Present => the notifications module holds the per-user
    # channels back so the end of the run can send ONE consolidated
    # message per (farm, tree, leaf, severity). Absent => nothing will
    # flush them later, so the fan-out sends at once. Same contract as
    # AlertOpenedV1.run_id.
    run_id: UUID | None = None
    # The aggregation identity the digest groups on. Carried so the
    # digest does not have to re-derive it from the row.
    group_key: str | None = None


class EvaluationRunFinishedV1(Event):
    """One decision-tree evaluation run has stopped writing.

    Published by every site that closes an eval run — the tenant sweep,
    the on-demand farm run, and the on-demand single-block run. The
    notifications module listens for it and sends the consolidated
    messages for every alert the run opened, which is why the run's
    alerts hold their per-user channels back while it is still going.

    It is published in a ``finally``, so a sweep that dies half way
    still flushes what it had opened. A second publish for the same
    run is harmless: the dispatch table's partial UNIQUE on
    ``(alert_id, channel, recipient_user_id, recipient_address)``
    turns the repeat into a no-op rather than a second email.
    """

    event_name: ClassVar[str] = "recommendations.evaluation_run_finished.v1"

    run_id: UUID
    tenant_schema: str
    # sweep | on_demand — carried for the log line, not for behaviour.
    kind: str = "sweep"


class RecommendationAppliedV1(Event):
    event_name: ClassVar[str] = "recommendations.recommendation_applied.v1"

    recommendation_id: UUID
    block_id: UUID
    tree_code: str
    actor_user_id: UUID | None = None


class RecommendationDismissedV1(Event):
    event_name: ClassVar[str] = "recommendations.recommendation_dismissed.v1"

    recommendation_id: UUID
    block_id: UUID
    tree_code: str
    actor_user_id: UUID | None = None
    dismissal_reason: str | None = None


class RecommendationDeferredV1(Event):
    event_name: ClassVar[str] = "recommendations.recommendation_deferred.v1"

    recommendation_id: UUID
    block_id: UUID
    tree_code: str
    actor_user_id: UUID | None = None
    deferred_until: datetime | None = None
