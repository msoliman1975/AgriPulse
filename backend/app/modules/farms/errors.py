"""Domain errors for the farms module.

All extend `app.core.errors.APIError` so the global handler turns them
into RFC 7807 problem+json responses with stable type URIs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://missionagre.io/problems"


class FarmNotFoundError(APIError):
    def __init__(self, farm_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Farm not found",
            detail=f"No farm with id {farm_id} in this tenant.",
            type_=f"{_TYPE_BASE}/farm-not-found",
            extras={"farm_id": str(farm_id)},
        )


class BlockNotFoundError(APIError):
    def __init__(self, block_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Block not found",
            detail=f"No block with id {block_id} in this tenant.",
            type_=f"{_TYPE_BASE}/block-not-found",
            extras={"block_id": str(block_id)},
        )


class CropAssignmentNotFoundError(APIError):
    def __init__(self, assignment_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop assignment not found",
            detail=f"No crop assignment with id {assignment_id} in this tenant.",
            type_=f"{_TYPE_BASE}/crop-assignment-not-found",
            extras={"assignment_id": str(assignment_id)},
        )


class CropNotFoundError(APIError):
    def __init__(self, crop_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop not found",
            detail=f"No active crop with id {crop_id} in the catalog.",
            type_=f"{_TYPE_BASE}/crop-not-found",
            extras={"crop_id": str(crop_id)},
        )


class FarmCodeConflictError(APIError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Farm code already in use",
            detail=f"Another farm in this tenant already uses code {code!r}.",
            type_=f"{_TYPE_BASE}/farm-code-conflict",
            extras={"code": code},
        )


class BlockCodeConflictError(APIError):
    def __init__(self, farm_id: UUID, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Block code already in use",
            detail=f"Another block in this farm already uses code {code!r}.",
            type_=f"{_TYPE_BASE}/block-code-conflict",
            extras={"farm_id": str(farm_id), "code": code},
        )


class GeometryInvalidError(APIError):
    def __init__(self, reason: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Geometry invalid",
            detail=reason,
            type_=f"{_TYPE_BASE}/geometry-invalid",
            extras=extra or {},
        )


class GeometryOutOfEgyptError(APIError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Geometry outside Egypt",
            detail=(
                "Geometry must lie within Egypt's bounding box "
                "(longitude 24..36, latitude 22..32)."
            ),
            type_=f"{_TYPE_BASE}/geometry-out-of-egypt",
        )


class FarmMembershipMissingError(APIError):
    def __init__(self, *, membership_id: UUID, tenant_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Membership not found",
            detail="The given membership does not belong to this tenant.",
            type_=f"{_TYPE_BASE}/membership-not-found",
            extras={
                "membership_id": str(membership_id),
                "tenant_id": str(tenant_id),
            },
        )


class FarmMemberAlreadyAssignedError(APIError):
    def __init__(self, *, membership_id: UUID, farm_id: UUID, role: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Member already assigned",
            detail="That membership already has this role on this farm.",
            type_=f"{_TYPE_BASE}/farm-member-already-assigned",
            extras={
                "membership_id": str(membership_id),
                "farm_id": str(farm_id),
                "role": role,
            },
        )
