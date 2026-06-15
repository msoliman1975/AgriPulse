"""Pydantic schemas for the resources module.

Workers carry a ``role`` (required) and an optional ``phone``;
equipment carries an ``equipment_type`` (required). Field-shape
validation runs in the schema; the DB CHECK constraint is a backstop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

ResourceKind = Literal["worker", "equipment"]

# U-2 (identity unification): worker roles share ONE canonical agronomic
# vocabulary with the IAM per-farm roles (app.shared.auth.context.FarmRole).
# Four of these are exactly FarmRole members — FarmManager / Agronomist /
# FieldOperator / Scout — so a person who logs in (a farm-scope) and a person
# who only does field work (a worker record) speak the same role language.
# `FieldWorker` is the worker-only extra (generic labour, no login/permission
# equivalent); FarmRole.Viewer is intentionally NOT a worker role (a read-only
# viewer does not perform plan activities). The migration that swaps the DB
# CHECK + backfills legacy lowercase values is 0043_resources_role_canonical.
# `test_worker_roles_align_with_farm_role` enforces the FarmRole alignment.
WorkerRole = Literal["FarmManager", "Agronomist", "FieldOperator", "Scout", "FieldWorker"]
EquipmentType = Literal["tractor", "sprayer", "irrigation_pump", "harvester", "other"]


class ResourceCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/resources body."""

    kind: ResourceKind
    name: str = Field(min_length=1, max_length=120)
    role: WorkerRole | None = None
    equipment_type: EquipmentType | None = None
    phone: str | None = Field(default=None, max_length=40)
    # U-3: optional link to a tenant member (membership_id). Workers only.
    membership_id: UUID | None = None

    @model_validator(mode="after")
    def _shape(self) -> ResourceCreateRequest:
        if self.kind == "worker":
            if self.role is None:
                raise PydanticCustomError("resource_worker_requires_role", "worker requires a role")
            if self.equipment_type is not None:
                raise PydanticCustomError(
                    "resource_worker_no_equipment_type",
                    "worker cannot carry an equipment_type",
                )
        else:
            if self.equipment_type is None:
                raise PydanticCustomError(
                    "resource_equipment_requires_type",
                    "equipment requires an equipment_type",
                )
            if self.role is not None:
                raise PydanticCustomError(
                    "resource_equipment_no_role",
                    "equipment cannot carry a role",
                )
            if self.phone is not None:
                raise PydanticCustomError(
                    "resource_equipment_no_phone",
                    "equipment cannot carry a phone",
                )
            if self.membership_id is not None:
                raise PydanticCustomError(
                    "resource_equipment_no_membership",
                    "equipment cannot be linked to a member",
                )
        return self


class ResourceUpdateRequest(BaseModel):
    """PATCH /api/v1/resources/{resource_id} body.

    Only the editable fields are surfaced. ``kind`` is immutable —
    delete + recreate to convert a worker to equipment.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: WorkerRole | None = None
    equipment_type: EquipmentType | None = None
    phone: str | None = Field(default=None, max_length=40)
    # U-3: set to a membership_id to link, or explicit null to unlink. Only
    # meaningful for workers; the service rejects it on equipment rows.
    membership_id: UUID | None = None
    archive: bool | None = None
    """If true, soft-archives. If false, restores from archive."""


class ResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    kind: ResourceKind
    name: str
    role: WorkerRole | None
    equipment_type: EquipmentType | None
    phone: str | None
    membership_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
