"""Domain errors for the farms module.

All extend `app.core.errors.APIError` so the global handler turns them
into RFC 7807 problem+json responses with stable type URIs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems"


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


class InvalidUnitTypeError(APIError):
    """Pivot/sector parent rules violated. Surfaces as 422.

    Raised when a pivot_sector references a parent that doesn't exist,
    isn't a pivot, or sits on a different farm â€” and when block/pivot
    rows try to set parent_unit_id (which is reserved for sectors).
    """

    def __init__(self, *, reason: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid land-unit type or parent",
            detail=reason,
            type_=f"{_TYPE_BASE}/invalid-unit-type",
            extras=extra or {},
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


class FarmAttachmentNotFoundError(APIError):
    def __init__(self, attachment_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Farm attachment not found",
            detail=f"No farm attachment with id {attachment_id} in this tenant.",
            type_=f"{_TYPE_BASE}/farm-attachment-not-found",
            extras={"attachment_id": str(attachment_id)},
        )


class BlockAttachmentNotFoundError(APIError):
    def __init__(self, attachment_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Block attachment not found",
            detail=f"No block attachment with id {attachment_id} in this tenant.",
            type_=f"{_TYPE_BASE}/block-attachment-not-found",
            extras={"attachment_id": str(attachment_id)},
        )


class AttachmentUploadMissingError(APIError):
    """Finalize was called but the S3 object isn't there."""

    def __init__(self, s3_key: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Attachment upload missing",
            detail="The S3 object for this attachment was not found. Re-upload before finalizing.",
            type_=f"{_TYPE_BASE}/attachment-upload-missing",
            extras={"s3_key": s3_key},
        )


class AttachmentUploadMismatchError(APIError):
    """Uploaded object's size or content-type doesn't match what init declared."""

    def __init__(
        self,
        *,
        s3_key: str,
        expected_size: int,
        actual_size: int,
        expected_content_type: str,
        actual_content_type: str,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Attachment upload mismatch",
            detail=(
                "The uploaded object's size or content-type differs from what "
                "was declared at init. Re-upload with matching values."
            ),
            type_=f"{_TYPE_BASE}/attachment-upload-mismatch",
            extras={
                "s3_key": s3_key,
                "expected_size": expected_size,
                "actual_size": actual_size,
                "expected_content_type": expected_content_type,
                "actual_content_type": actual_content_type,
            },
        )
