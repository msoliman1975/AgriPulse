"""Resources module domain errors."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError


class ResourceNotFoundError(APIError):
    def __init__(self, resource_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Resource not found",
            detail=f"resource {resource_id} does not exist or is not in this tenant",
            type_="https://agripulse.cloud/problems/resource-not-found",
        )


class DuplicateResourceNameError(APIError):
    def __init__(self, name: str, kind: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Resource name already in use",
            detail=f"another active {kind} on this farm is already named {name!r}",
            type_="https://agripulse.cloud/problems/resource-duplicate-name",
        )


class InvalidResourceShapeError(APIError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid resource shape",
            detail=detail,
            type_="https://agripulse.cloud/problems/resource-invalid",
        )
