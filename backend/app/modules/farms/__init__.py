"""Farms domain — agronomic core: farms, blocks, crop assignments, attachments.

Public surface (importable by other modules and `app/main.py`):

  - `app.modules.farms.service.FarmService`  (Protocol)
  - `app.modules.farms.events.*`             (FarmCreatedV1, BlockCreatedV1, ...)
  - `app.modules.farms.router.router`        (FastAPI router)

See ARCHITECTURE.md § 6 (module map) and data_model.md § 5.
"""

from app.modules.farms.events import (
    BlockAttachmentDeletedV1,
    BlockAttachmentUploadedV1,
    BlockBoundaryChangedV1,
    BlockCreatedV1,
    BlockCropAssignedV1,
    BlockCropUpdatedV1,
    BlockInactivatedV1,
    BlockReactivatedV1,
    BlockUpdatedV1,
    FarmAttachmentDeletedV1,
    FarmAttachmentUploadedV1,
    FarmBoundaryChangedV1,
    FarmCreatedV1,
    FarmInactivatedV1,
    FarmMemberAssignedV1,
    FarmMemberRevokedV1,
    FarmReactivatedV1,
    FarmUpdatedV1,
)
from app.modules.farms.service import FarmService, get_farm_service

__all__ = [
    "BlockAttachmentDeletedV1",
    "BlockAttachmentUploadedV1",
    "BlockBoundaryChangedV1",
    "BlockCreatedV1",
    "BlockCropAssignedV1",
    "BlockCropUpdatedV1",
    "BlockInactivatedV1",
    "BlockReactivatedV1",
    "BlockUpdatedV1",
    "FarmAttachmentDeletedV1",
    "FarmAttachmentUploadedV1",
    "FarmBoundaryChangedV1",
    "FarmCreatedV1",
    "FarmInactivatedV1",
    "FarmMemberAssignedV1",
    "FarmMemberRevokedV1",
    "FarmReactivatedV1",
    "FarmService",
    "FarmUpdatedV1",
    "get_farm_service",
]
