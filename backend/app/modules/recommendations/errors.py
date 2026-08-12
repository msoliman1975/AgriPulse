"""Domain errors for the recommendations module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems/recommendations"


class RecommendationNotFoundError(APIError):
    def __init__(self, recommendation_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Recommendation not found",
            detail=f"No recommendation with id {recommendation_id} in this tenant.",
            type_=f"{_TYPE_BASE}/recommendation-not-found",
            extras={"recommendation_id": str(recommendation_id)},
        )


class DecisionTreeNotFoundError(APIError):
    def __init__(self, tree_code: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Decision tree not found",
            detail=f"No active decision tree with code {tree_code!r}.",
            type_=f"{_TYPE_BASE}/decision-tree-not-found",
            extras={"tree_code": tree_code},
        )


class BlockNotInFarmError(APIError):
    """The block exists but does not belong to the farm the caller named.

    Raised by the tree-explain endpoint, which authorizes against a
    ``farm_id`` query parameter so farm-scoped users resolve. Without this
    check a user scoped to farm A could pass farm A for authorization and a
    block from farm B for the read.
    """

    def __init__(self, *, block_id: UUID, farm_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Block not found in farm",
            detail=f"Block {block_id} does not belong to farm {farm_id}.",
            type_=f"{_TYPE_BASE}/block-not-in-farm",
            extras={"block_id": str(block_id), "farm_id": str(farm_id)},
        )


class InvalidRecommendationTransitionError(APIError):
    """Caller asked to apply / dismiss / defer a recommendation in a
    state that doesn't allow it."""

    def __init__(self, *, current_state: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Invalid recommendation state transition",
            detail=(f"Cannot {action} a recommendation whose current state is {current_state!r}."),
            type_=f"{_TYPE_BASE}/invalid-transition",
            extras={"current_state": current_state, "action": action},
        )


class DecisionTreeParseError(APIError):
    """A YAML decision tree *shipped with the server* is malformed or
    references unknown fields — a deployment problem, hence 5xx.

    The authoring API compiles caller-supplied YAML through the same
    loader, so this can also be raised on a request. There it is the
    caller's YAML that is wrong, not the server's: those call sites wrap
    it in ``InvalidTreeYamlError`` (422) instead of letting a 500 out.
    """

    def __init__(self, *, path: str, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Decision tree parse error",
            detail=f"{path}: {detail}",
            type_=f"{_TYPE_BASE}/decision-tree-parse-error",
            extras={"path": path},
        )
        self.path = path
        self.reason = detail


class InvalidTreeYamlError(APIError):
    """Caller-supplied decision-tree YAML failed to compile.

    A 422 rather than the loader's 500: the request body is what's wrong.
    The loader tags its messages with a source path (``<api:my_tree>``)
    that means nothing to an author, so it is dropped here.
    """

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid decision tree YAML",
            detail=reason,
            type_=f"{_TYPE_BASE}/invalid-tree-yaml",
        )

    @classmethod
    def from_parse_error(cls, exc: DecisionTreeParseError) -> InvalidTreeYamlError:
        return cls(reason=getattr(exc, "reason", None) or (exc.detail or "malformed tree YAML"))
