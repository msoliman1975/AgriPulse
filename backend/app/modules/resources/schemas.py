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
WorkerRole = Literal["agronomist", "operator", "scout", "field_worker", "manager"]
EquipmentType = Literal["tractor", "sprayer", "irrigation_pump", "harvester", "other"]


class ResourceCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/resources body."""

    kind: ResourceKind
    name: str = Field(min_length=1, max_length=120)
    role: WorkerRole | None = None
    equipment_type: EquipmentType | None = None
    phone: str | None = Field(default=None, max_length=40)

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
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
