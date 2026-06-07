"""CS-13 unit tests — reference scanning + conflict-aware archive.

Repo mocked. Covers the compiled-tree walk, the definition/template
reference assembly, and the 409 in-use guard (with force override).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.signals.errors import (
    SignalDefinitionInUseError,
    SignalTemplateInUseError,
)
from app.modules.signals.service import SignalsServiceImpl, _tree_signal_codes


def _impl(repo: AsyncMock) -> SignalsServiceImpl:
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = MagicMock()
    impl._log = None  # type: ignore[attr-defined]
    return impl


# A compiled tree with a nested signal ref (CS-7 D6 leaf shape).
_TREE = {
    "root": "n1",
    "nodes": {
        "n1": {
            "condition": {
                "op": "gt",
                "left": {"source": "signals", "code": "soil_ph", "key": "value_numeric"},
                "right": 7.0,
            }
        }
    },
}


def test_tree_signal_codes_walks_nested_refs() -> None:
    assert _tree_signal_codes(_TREE) == {"soil_ph"}


def test_tree_signal_codes_tolerates_json_string() -> None:
    import json

    assert _tree_signal_codes(json.dumps(_TREE)) == {"soil_ph"}


def test_tree_signal_codes_ignores_unrelated() -> None:
    assert _tree_signal_codes({"x": {"source": "weather", "code": "soil_ph"}}) == set()


@pytest.mark.asyncio
async def test_definition_references_collects_trees_and_templates() -> None:
    def_id, tree_id, tpl_id = uuid4(), uuid4(), uuid4()
    repo = AsyncMock()
    repo.get_definition = AsyncMock(return_value={"id": def_id, "code": "soil_ph"})
    repo.list_active_tree_versions = AsyncMock(
        return_value=(
            {"id": tree_id, "code": "wheat", "name": "Wheat", "compiled": _TREE},
            {"id": uuid4(), "code": "other", "name": "Other", "compiled": {"nodes": {}}},
        )
    )
    repo.list_templates_for_definition = AsyncMock(
        return_value=({"id": tpl_id, "code": "soiltest", "name": "Soil test"},)
    )
    refs = await _impl(repo).get_definition_references(definition_id=def_id, tenant_id=uuid4())

    assert [t["id"] for t in refs["decision_trees"]] == [str(tree_id)]
    assert refs["decision_trees"][0]["kind"] == "decision_tree"
    assert [t["id"] for t in refs["templates"]] == [str(tpl_id)]


@pytest.mark.asyncio
async def test_delete_definition_blocks_when_referenced() -> None:
    def_id = uuid4()
    repo = AsyncMock()
    repo.get_definition = AsyncMock(return_value={"id": def_id, "code": "soil_ph"})
    repo.list_active_tree_versions = AsyncMock(
        return_value=({"id": uuid4(), "code": "w", "name": "W", "compiled": _TREE},)
    )
    repo.list_templates_for_definition = AsyncMock(return_value=())
    impl = _impl(repo)

    with pytest.raises(SignalDefinitionInUseError):
        await impl.delete_definition(
            definition_id=def_id, actor_user_id=None, tenant_schema="t", tenant_id=uuid4()
        )
    repo.soft_delete_definition.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_definition_force_overrides_guard() -> None:
    def_id = uuid4()
    repo = AsyncMock()
    repo.get_definition = AsyncMock(return_value={"id": def_id, "code": "soil_ph"})
    repo.soft_delete_definition = AsyncMock(return_value=True)
    impl = _impl(repo)

    await impl.delete_definition(
        definition_id=def_id,
        actor_user_id=None,
        tenant_schema="t",
        tenant_id=uuid4(),
        force=True,
    )
    # Guard skipped — no reference scan, soft-delete ran, louder audit event.
    repo.list_active_tree_versions.assert_not_awaited()
    repo.soft_delete_definition.assert_awaited_once()
    assert impl._audit.record.await_args.kwargs["event_type"] == (
        "signals.definition_force_deleted"
    )


@pytest.mark.asyncio
async def test_delete_template_blocks_when_member_referenced() -> None:
    tpl_id = uuid4()
    repo = AsyncMock()
    repo.get_template = AsyncMock(return_value={"id": tpl_id, "code": "soiltest"})
    repo.get_template_member_codes = AsyncMock(return_value=("soil_ph",))
    repo.list_active_tree_versions = AsyncMock(
        return_value=({"id": uuid4(), "code": "w", "name": "W", "compiled": _TREE},)
    )
    impl = _impl(repo)

    with pytest.raises(SignalTemplateInUseError):
        await impl.delete_template(
            template_id=tpl_id, actor_user_id=None, tenant_schema="t", tenant_id=uuid4()
        )
    repo.soft_delete_template.assert_not_awaited()
