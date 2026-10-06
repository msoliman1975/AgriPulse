"""Investors module domain errors."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_PROBLEM = "https://agripulse.cloud/problems/"


class InvestorNotFoundError(APIError):
    def __init__(self, investor_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=f"investor {investor_id} does not exist or is not in this tenant",
            type_=_PROBLEM + "investor-not-found",
        )


class HoldingNotFoundError(APIError):
    def __init__(self, holding_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Holding not found",
            detail=f"holding {holding_id} does not exist on this farm",
            type_=_PROBLEM + "holding-not-found",
        )


class OwnershipNotFoundError(APIError):
    def __init__(self, ownership_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Ownership not found",
            detail=f"ownership {ownership_id} does not exist on this farm",
            type_=_PROBLEM + "holding-ownership-not-found",
        )


class InvestorConflictError(APIError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Investor already exists",
            detail=detail,
            type_=_PROBLEM + "investor-conflict",
        )


class HoldingCodeTakenError(APIError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Holding code already in use",
            detail=f"another holding already uses the code {code!r}",
            type_=_PROBLEM + "holding-code-taken",
        )


class HoldingGeometryError(APIError):
    """The polygon itself is not usable: malformed, self-crossing, or with holes."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=422,
            title="Holding shape is not valid",
            detail=detail,
            type_=_PROBLEM + "holding-geometry-invalid",
        )


class HoldingOutsideBlockError(APIError):
    """Rule R1."""

    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            title="Holding is outside its block",
            detail="Every point of a holding must lie inside its block.",
            type_=_PROBLEM + "holding-outside-block",
        )


class HoldingOverlapError(APIError):
    """Rule R2."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Holding overlaps another holding",
            detail="Holdings in one block may share an edge but must not overlap.",
            type_=_PROBLEM + "holding-overlap",
        )


class BlockNotEligibleError(APIError):
    """Rule R4, and blocks that are archived or missing."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=422,
            title="Block cannot hold holdings",
            detail=detail,
            type_=_PROBLEM + "holding-block-not-eligible",
        )


class HoldingOwnedError(APIError):
    """Rules R7 and R8: the action needs the holding to have no owner."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Holding has an owner",
            detail=detail,
            type_=_PROBLEM + "holding-owned",
        )


class OwnershipConflictError(APIError):
    """Rule R9 and the transfer date rules."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Ownership dates conflict",
            detail=detail,
            type_=_PROBLEM + "holding-ownership-conflict",
        )


class BlockHasHoldingsError(APIError):
    """Rules R6 and R7, raised from the farms module."""

    def __init__(self, detail: str, *, holding_codes: list[str]) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Block has holdings",
            detail=detail,
            type_=_PROBLEM + "block-has-holdings",
            extras={"holding_codes": holding_codes},
        )
