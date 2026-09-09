"""A platform tree that a tenant cannot edit must say so, not read as missing.

Every authoring write scopes its lookup to the caller's own tenant, because a
platform tree is owned by its YAML file: `sync_from_disk` rewrites it at the
next startup whose compiled hash differs, so a tenant's edit would live until
the next restart and then vanish with no message.

The scoped lookup cannot tell "no such tree" from "not yours", and it reported
both as missing. "No decision tree with code 'mango_canopy_vigour_by_size_v1'"
about a tree the author had open on screen sent somebody hunting a data
problem that did not exist — and since all 33 shipped trees are platform
trees, it was every shipped tree.

The lookup itself is unchanged, so this covers the branch, not the SQL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.recommendations.router import _map_authoring_error
from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _DecisionTreeNotFoundError,
    _PlatformTreeNotEditableError,
)

_TENANT = uuid4()
_PLATFORM_TREE = {"id": uuid4(), "code": "mango_canopy_vigour_by_size_v1", "tenant_id": None}
_OWN_TREE = {"id": uuid4(), "code": "my_tree_v1", "tenant_id": _TENANT}


class _Repo:
    """Answers `get_tree_by_code` the way the real one does.

    `scope_tenant_id=None` means platform trees only; a UUID means that
    tenant's own trees only, unless `include_platform` widens it.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[UUID | None] = []

    async def get_tree_by_code(
        self, code: str, *, scope_tenant_id: UUID | None, **_: Any
    ) -> dict[str, Any] | None:
        self.calls.append(scope_tenant_id)
        for row in self.rows:
            if row["code"] == code and row["tenant_id"] == scope_tenant_id:
                return row
        return None


def _service(rows: list[dict[str, Any]], *, tenant_id: UUID | None) -> Any:
    service = DecisionTreesAuthorService.__new__(DecisionTreesAuthorService)
    service._repo = _Repo(rows)  # type: ignore[attr-defined]
    service._tenant_id = tenant_id  # type: ignore[attr-defined]
    return service


@pytest.mark.asyncio
async def test_a_tenant_editing_a_platform_tree_is_told_what_is_true() -> None:
    service = _service([_PLATFORM_TREE], tenant_id=_TENANT)

    with pytest.raises(_PlatformTreeNotEditableError) as err:
        await service._own_tree_or_raise("mango_canopy_vigour_by_size_v1")

    assert err.value.code == "mango_canopy_vigour_by_size_v1"
    assert "platform" in str(err.value).lower()


@pytest.mark.asyncio
async def test_that_error_is_a_403_not_a_404() -> None:
    """The tree is there and the caller can read it. What they cannot do is
    change it, and that is 403."""
    mapped = _map_authoring_error(_PlatformTreeNotEditableError("t_ndvi_canopy_vigour"))

    assert mapped is not None
    assert mapped.status_code == 403  # type: ignore[attr-defined]
    assert mapped.extras == {"code": "t_ndvi_canopy_vigour"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_code_that_exists_nowhere_is_still_a_404() -> None:
    service = _service([_PLATFORM_TREE], tenant_id=_TENANT)

    with pytest.raises(_DecisionTreeNotFoundError):
        await service._own_tree_or_raise("no_such_tree_v1")


@pytest.mark.asyncio
async def test_the_tenants_own_tree_comes_back() -> None:
    service = _service([_OWN_TREE, _PLATFORM_TREE], tenant_id=_TENANT)

    assert await service._own_tree_or_raise("my_tree_v1") == _OWN_TREE


@pytest.mark.asyncio
async def test_the_second_lookup_only_runs_on_the_failure_path() -> None:
    """The happy path must not pay for the better error message."""
    service = _service([_OWN_TREE], tenant_id=_TENANT)

    await service._own_tree_or_raise("my_tree_v1")

    assert service._repo.calls == [_TENANT]


@pytest.mark.asyncio
async def test_a_platform_caller_edits_platform_trees_normally() -> None:
    """Nothing here narrows what the platform itself may do: a caller with no
    tenant is scoped to platform trees, and finds them."""
    service = _service([_PLATFORM_TREE], tenant_id=None)

    assert await service._own_tree_or_raise("mango_canopy_vigour_by_size_v1") == _PLATFORM_TREE
