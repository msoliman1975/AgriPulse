"""Farms domain — agronomic core: farms, blocks, crop assignments, attachments.

Public surface (importable by other modules and `app/main.py`):

  - `app.modules.farms.service.FarmService`  (Protocol)
  - `app.modules.farms.events.*`             (FarmCreatedV1, BlockCreatedV1, ...)
  - `app.modules.farms.router.router`        (FastAPI router)

See ARCHITECTURE.md § 6 (module map) and data_model.md § 5.
"""

from app.modules.farms.events import (
    BlockArchivedV1,
    BlockBoundaryChangedV1,
    BlockCreatedV1,
    BlockCropAssignedV1,
    BlockCropUpdatedV1,
    BlockUpdatedV1,
    FarmArchivedV1,
    FarmBoundaryChangedV1,
    FarmCreatedV1,
    FarmMemberAssignedV1,
    FarmMemberRevokedV1,
    FarmUpdatedV1,
)
from app.modules.farms.service import FarmService, get_farm_service

__all__ = [
    "BlockArchivedV1",
    "BlockBoundaryChangedV1",
    "BlockCreatedV1",
    "BlockCropAssignedV1",
    "BlockCropUpdatedV1",
    "BlockUpdatedV1",
    "FarmArchivedV1",
    "FarmBoundaryChangedV1",
    "FarmCreatedV1",
    "FarmMemberAssignedV1",
    "FarmMemberRevokedV1",
    "FarmService",
    "FarmUpdatedV1",
    "get_farm_service",
]
