"""Public event types for the farms module.

Cross-module reactions (audit, imagery in P3, alerts in P4, ...) subscribe
via `app.shared.eventbus`. Class names are versioned (`...V1`); the
event_name string mirrors the class name in dotted form.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class FarmCreatedV1(Event):
    event_name: ClassVar[str] = "farms.farm_created.v1"

    farm_id: UUID
    code: str
    name: str
    area_m2: Decimal
    actor_user_id: UUID | None = None
    created_at: datetime


class FarmUpdatedV1(Event):
    event_name: ClassVar[str] = "farms.farm_updated.v1"

    farm_id: UUID
    changed_fields: tuple[str, ...]
    actor_user_id: UUID | None = None


class FarmArchivedV1(Event):
    event_name: ClassVar[str] = "farms.farm_archived.v1"

    farm_id: UUID
    actor_user_id: UUID | None = None


class FarmBoundaryChangedV1(Event):
    """Emitted whenever a farm's boundary is replaced.

    Carries the new centroid so downstream consumers (imagery in P3) can
    decide whether to invalidate caches before they look at the row.
    """

    event_name: ClassVar[str] = "farms.farm_boundary_changed.v1"

    farm_id: UUID
    new_centroid_lon: float
    new_centroid_lat: float
    actor_user_id: UUID | None = None


class BlockCreatedV1(Event):
    event_name: ClassVar[str] = "farms.block_created.v1"

    block_id: UUID
    farm_id: UUID
    code: str
    area_m2: Decimal
    aoi_hash: str
    actor_user_id: UUID | None = None


class BlockUpdatedV1(Event):
    event_name: ClassVar[str] = "farms.block_updated.v1"

    block_id: UUID
    changed_fields: tuple[str, ...]
    actor_user_id: UUID | None = None


class BlockBoundaryChangedV1(Event):
    """Emitted whenever a block's boundary is replaced.

    Carries `prev_aoi_hash` and `new_aoi_hash` so imagery (P3) can detect
    that any cached scenes keyed by the old hash are stale.
    """

    event_name: ClassVar[str] = "farms.block_boundary_changed.v1"

    block_id: UUID
    farm_id: UUID
    prev_aoi_hash: str
    new_aoi_hash: str
    actor_user_id: UUID | None = None


class BlockArchivedV1(Event):
    event_name: ClassVar[str] = "farms.block_archived.v1"

    block_id: UUID
    farm_id: UUID
    actor_user_id: UUID | None = None


class BlockCropAssignedV1(Event):
    event_name: ClassVar[str] = "farms.block_crop_assigned.v1"

    block_crop_id: UUID
    block_id: UUID
    crop_id: UUID
    crop_variety_id: UUID | None = None
    season_label: str
    actor_user_id: UUID | None = None


class BlockCropUpdatedV1(Event):
    event_name: ClassVar[str] = "farms.block_crop_updated.v1"

    block_crop_id: UUID
    block_id: UUID
    changed_fields: tuple[str, ...]
    actor_user_id: UUID | None = None


class FarmMemberAssignedV1(Event):
    event_name: ClassVar[str] = "farms.farm_member_assigned.v1"

    farm_scope_id: UUID
    membership_id: UUID
    farm_id: UUID
    role: str
    actor_user_id: UUID | None = None


class FarmMemberRevokedV1(Event):
    event_name: ClassVar[str] = "farms.farm_member_revoked.v1"

    farm_scope_id: UUID
    membership_id: UUID
    farm_id: UUID
    actor_user_id: UUID | None = None
