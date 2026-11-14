"""Domain errors for the plan-templates module (RFC 7807 via APIError)."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems/plan-templates"


class PlanTemplateNotFoundError(APIError):
    def __init__(self, template_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Plan template not found",
            detail=f"No plan template with id {template_id}.",
            type_=f"{_TYPE_BASE}/not-found",
            extras={"template_id": str(template_id)},
        )


class PlanTemplateConflictError(APIError):
    def __init__(self, *, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Plan template code already in use",
            detail=f"Another plan template already uses code {code!r}.",
            type_=f"{_TYPE_BASE}/conflict",
            extras={"code": code},
        )


class PlanTemplateValidationError(APIError):
    """Bad authoring payload — unknown stage_code, milestone ref, etc. 422."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid plan template",
            detail=reason,
            type_=f"{_TYPE_BASE}/validation",
        )


class AllocationNotFoundError(APIError):
    def __init__(self, allocation_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Saved plan not found",
            detail=f"No saved plan with id {allocation_id}.",
            type_=f"{_TYPE_BASE}/allocation-not-found",
            extras={"allocation_id": str(allocation_id)},
        )


class AllocationBlocksRejectedError(APIError):
    """Blocks whose crop doesn't match the manual (decision C3). 422."""

    def __init__(self, *, blocks: list[dict[str, object]]) -> None:
        codes = ", ".join(str(b.get("block_code") or b.get("block_id")) for b in blocks)
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Blocks don't match this manual",
            detail=f"These blocks grow a different crop or variety: {codes}.",
            type_=f"{_TYPE_BASE}/allocation-blocks-rejected",
            extras={"blocks": [{k: str(v) for k, v in b.items()} for b in blocks]},
        )
