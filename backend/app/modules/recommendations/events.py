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
