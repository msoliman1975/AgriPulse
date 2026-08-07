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


class CropVarietyNotFoundError(APIError):
    def __init__(self, variety_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop variety not found",
            detail=f"No crop variety with id {variety_id} in the catalog.",
            type_=f"{_TYPE_BASE}/crop-variety-not-found",
            extras={"crop_variety_id": str(variety_id)},
        )


class CropStrainNotFoundError(APIError):
    def __init__(self, strain_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop strain not found",
            detail=f"No crop strain with id {strain_id} in the catalog.",
            type_=f"{_TYPE_BASE}/crop-strain-not-found",
            extras={"crop_variety_strain_id": str(strain_id)},
        )


class CountryNotFoundError(APIError):
    def __init__(self, country_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Country not found",
            detail=f"No country with id {country_id} in the catalog.",
            type_=f"{_TYPE_BASE}/country-not-found",
            extras={"country_id": str(country_id)},
        )


class UnknownCountryCodeError(APIError):
    """A farm write referenced a ``country_code`` not in the active catalog. 422."""

    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unknown country code",
            detail=f"Country code {code!r} is not an active country in the catalog.",
            type_=f"{_TYPE_BASE}/unknown-country-code",
            extras={"country_code": code},
        )


class CountryCodeConflictError(APIError):
    """A new country's code collides with an existing one (codes are unique). 409."""

    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Country code already in use",
            detail=f"Another country already uses code {code!r}.",
            type_=f"{_TYPE_BASE}/country-code-conflict",
            extras={"code": code},
        )


class CropCatalogConflictError(APIError):
    """A crop / variety / strain code collides with an existing sibling
    (the catalog enforces unique codes per level). Surfaces as 409."""

    def __init__(self, *, level: str, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Crop catalog code already in use",
            detail=f"Another {level} already uses code {code!r} at this level.",
            type_=f"{_TYPE_BASE}/crop-catalog-conflict",
            extras={"level": level, "code": code},
        )


class CropCatalogValidationError(APIError):
    """A ``phenology_stages`` / ``size_classes`` payload has a bad shape or a
    mode that doesn't fit the crop's cycle (perennial vs annual). 422."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid crop catalog payload",
            detail=reason,
            type_=f"{_TYPE_BASE}/crop-catalog-validation",
        )


class CropAttributeDefinitionNotFoundError(APIError):
    def __init__(self, definition_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop attribute definition not found",
            detail=f"No crop attribute definition with id {definition_id} in the catalog.",
            type_=f"{_TYPE_BASE}/crop-attribute-definition-not-found",
            extras={"definition_id": str(definition_id)},
        )


class CropAttributeCodeConflictError(APIError):
    """Two definitions with the same ``code`` on the same taxonomy node.

    Not merely a uniqueness nicety: deepest-wins resolution picks one winner
    per code per level, so a duplicate would make which definition an author
    sees depend on row order. 409.
    """

    def __init__(self, *, path: str, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Crop attribute code already in use",
            detail=f"An attribute with code {code!r} is already defined on {path!r}.",
            type_=f"{_TYPE_BASE}/crop-attribute-code-conflict",
            extras={"path": path, "code": code},
        )


class CropAttributeReservedCodeError(APIError):
    """The requested code is already a first-class block field.

    Allowing it would put two entries with the same name in the decision-tree
    condition builder, one of which never resolves. 422.
    """

    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Reserved crop attribute code",
            detail=(
                f"{code!r} is already a first-class block or crop field. Pick a "
                "different code — an attribute may not shadow one."
            ),
            type_=f"{_TYPE_BASE}/crop-attribute-reserved-code",
            extras={"code": code},
        )


class CropAttributeValidationError(APIError):
    """A definition payload is internally inconsistent, or its gate points at
    something unusable (missing sibling, wrong type, forward reference). 422."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid crop attribute definition",
            detail=reason,
            type_=f"{_TYPE_BASE}/crop-attribute-validation",
        )


class CropAssignmentOverlapError(APIError):
    """A block may hold one crop at a time; the proposed range collides. 409.

    Named deliberately: the DB's exclusion constraint would reject this as an
    opaque IntegrityError, and "which crop, from when to when" is the only
    thing that lets a user fix it without going hunting.
    """

    def __init__(self, *, crop_path: str, existing_from: Any, existing_to: Any) -> None:
        until = str(existing_to) if existing_to else "ongoing"
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Crop assignment overlaps an existing one",
            detail=(
                f"This block is already under {crop_path!r} from {existing_from} "
                f"to {until}. One crop at a time per block — end that assignment "
                "first, or start this one after it."
            ),
            type_=f"{_TYPE_BASE}/crop-assignment-overlap",
            extras={
                "crop_path": crop_path,
                "effective_from": str(existing_from),
                "effective_to": str(existing_to) if existing_to else None,
            },
        )


class CropAssignmentRangeError(APIError):
    """`valid to` is not after `valid from`. 422."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid assignment date range",
            detail=reason,
            type_=f"{_TYPE_BASE}/crop-assignment-range",
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


class CropTaxonomyError(APIError):
    """A crop assignment violates the crop's classification depth — e.g.
    a variety_strain crop missing its strain, or a crop_only crop given a
    variety. Surfaces as 422."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid crop taxonomy selection",
            detail=reason,
            type_=f"{_TYPE_BASE}/invalid-crop-taxonomy",
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


class CategoryLockedError(APIError):
    """A write to a block-side field that lives in a locked Shared category."""

    def __init__(self, *, farm_id: UUID, category: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Category locked",
            detail=(
                f"Category {category!r} is centrally managed by the farm "
                f"template. Unlock it before editing the corresponding fields."
            ),
            type_=f"{_TYPE_BASE}/category-locked",
            extras={"farm_id": str(farm_id), "category": category},
        )


class LockDivergenceError(APIError):
    """Attempted to lock a category while blocks diverge from the template.

    The diff payload lets the UI render a "Lock and overwrite" confirm
    modal that resubmits with force_overwrite=true.
    """

    def __init__(self, *, farm_id: UUID, category: str, diff: dict[str, Any]) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Lock would overwrite blocks",
            detail=(
                f"Locking {category!r} would overwrite divergent blocks. Resubmit "
                f"with force_overwrite=true to apply the template first."
            ),
            type_=f"{_TYPE_BASE}/lock-divergence",
            extras={"farm_id": str(farm_id), "category": category, "diff": diff},
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
