"""Public event types for the imagery module.

Cross-module reactions (audit, analytics in P5, alerts in P4) subscribe
via `app.shared.eventbus`. Class names are versioned (`...V1`); the
`event_name` string mirrors the class name in dotted form.

`IndexAggregatedV1` lives here rather than in `indices/events.py`
because it is emitted by the imagery pipeline's `compute_indices` task —
the indices module exposes a Service Protocol that imagery calls into,
not a parallel set of events. Subscribers that care about new index
data subscribe to this single event regardless of which module owns
the producing code.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class SubscriptionCreatedV1(Event):
    """A block was subscribed to an imagery product."""

    event_name: ClassVar[str] = "imagery.subscription_created.v1"

    subscription_id: UUID
    block_id: UUID
    product_id: UUID
    actor_user_id: UUID | None = None


class SubscriptionRevokedV1(Event):
    """A block's subscription was soft-revoked (`is_active=false`)."""

    event_name: ClassVar[str] = "imagery.subscription_revoked.v1"

    subscription_id: UUID
    block_id: UUID
    actor_user_id: UUID | None = None


class SceneDiscoveredV1(Event):
    """A new candidate scene was found for a subscription's AOI / time window."""

    event_name: ClassVar[str] = "imagery.scene_discovered.v1"

    job_id: UUID
    subscription_id: UUID
    block_id: UUID
    scene_id: str
    scene_datetime: datetime
    cloud_cover_pct: Decimal | None = None


class SceneIngestedV1(Event):
    """A scene's raw bands COG and STAC item were registered successfully."""

    event_name: ClassVar[str] = "imagery.scene_ingested.v1"

    job_id: UUID
    block_id: UUID
    scene_id: str
    stac_item_id: str
    valid_pixel_pct: Decimal | None = None


class SceneSkippedV1(Event):
    """A scene was deliberately not ingested (cloud, duplicate, out_of_window)."""

    event_name: ClassVar[str] = "imagery.scene_skipped.v1"

    job_id: UUID
    reason: str  # 'cloud' | 'duplicate' | 'out_of_window'


class IngestionFailedV1(Event):
    """A scene's ingestion pipeline raised; the job row was set to `failed`."""

    event_name: ClassVar[str] = "imagery.ingestion_failed.v1"

    job_id: UUID
    error: str


class IndexAggregatedV1(Event):
    """A row was inserted into block_index_aggregates for a (block, time, index)."""

    event_name: ClassVar[str] = "imagery.index_aggregated.v1"

    block_id: UUID
    index_code: str
    time: datetime
    valid_pixel_pct: Decimal | None = None
