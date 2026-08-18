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


class GroupMemberNotActionableError(APIError):
    """Caller addressed a per-cell member of a group instead of the group.

    Members are evidence, not work items: they carry a cell's own snapshot so
    the map can colour it and the drill-down can list it, but the thing a
    supervisor decides about is the whole group. Acting on one member would
    leave the group open with a hole in it and the other cells' dedup keys
    still occupied. The parent's id travels on the error so a client that
    followed a stale link can retry against the right row rather than guess.
    """

    def __init__(self, *, recommendation_id: UUID, parent_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Recommendation is part of a group",
            detail=(
                f"Recommendation {recommendation_id} is one cell of an aggregated "
                f"item. Act on the group ({parent_id}) instead."
            ),
            type_=f"{_TYPE_BASE}/group-member-not-actionable",
            extras={
                "recommendation_id": str(recommendation_id),
                "group_parent_id": str(parent_id),
            },
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


class FarmNotFoundError(APIError):
    """Named farm is absent (or archived) in this tenant.

    Checked before a tree run opens its run row: an unknown farm has no
    active blocks, so without this the run would close with every counter
    at zero and read as "the tree matched nothing" rather than "that farm
    does not exist."
    """

    def __init__(self, farm_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Farm not found",
            detail=f"No farm with id {farm_id} in this tenant.",
            type_=f"{_TYPE_BASE}/farm-not-found",
            extras={"farm_id": str(farm_id)},
        )


class DecisionTreeNotRunnableError(APIError):
    """The tree exists but the evaluator would never reach it.

    Archived, deactivated, or never published — the three states in which
    the nightly sweep silently skips a tree. Running one on demand has to
    refuse for the same reason: the run would write nothing and the author
    would read that as "my conditions did not match."
    """

    def __init__(self, tree_code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Decision tree is not runnable",
            detail=(
                f"Decision tree {tree_code!r} is archived, inactive, or has no "
                "published version, so the evaluator would skip it. Publish a "
                "version and make sure the tree is active, then run again."
            ),
            type_=f"{_TYPE_BASE}/decision-tree-not-runnable",
            extras={"tree_code": tree_code},
        )
