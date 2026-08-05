"""Cross-language guard: the frontend condition builder knows every backend source.

`frontend/src/modules/decisionTrees/lib/conditionEdit.ts` mirrors the backend
value-ref union as a hand-maintained TypeScript union. When those drifted
apart once before (#345), nothing errored — the visual builder silently
demoted every tree using the new source to the read-only YAML fallback, which
looks like the feature was never built rather than like a bug.

The per-constant assertions live on the frontend side
(`conditionEdit.test.ts`); this test pins the thing neither side can check
alone: that the two *source* vocabularies are identical.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from app.shared.conditions.models import ValueRef

# tests/unit/shared/<this file> → parents[3] is backend/, parents[4] the repo root.
_CONDITION_EDIT_TS = (
    Path(__file__).resolve().parents[4]
    / "frontend"
    / "src"
    / "modules"
    / "decisionTrees"
    / "lib"
    / "conditionEdit.ts"
)


def _backend_sources() -> set[str]:
    """The ``source`` literal of every member of the backend ValueRef union."""
    sources: set[str] = set()
    for member in typing.get_args(ValueRef):
        annotation = typing.get_type_hints(member)["source"]
        sources.update(typing.get_args(annotation))
    return sources


def _frontend_sources(text: str) -> set[str]:
    """Members of the ``ValueRefSource`` union in conditionEdit.ts."""
    match = re.search(r"export type ValueRefSource\s*=([^;]+);", text)
    assert match, "ValueRefSource union not found — did conditionEdit.ts move?"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


@pytest.mark.skipif(
    not _CONDITION_EDIT_TS.exists(),
    reason="frontend tree not checked out (backend-only container build)",
)
def test_frontend_and_backend_condition_sources_match() -> None:
    text = _CONDITION_EDIT_TS.read_text(encoding="utf-8")
    frontend = _frontend_sources(text)
    backend = _backend_sources()

    assert frontend == backend, (
        "condition source drift — the visual builder degrades silently, it does "
        f"not error.\n  only in backend: {sorted(backend - frontend)}"
        f"\n  only in frontend: {sorted(frontend - backend)}"
        "\nAdd the source to conditionEdit.ts (union, parser, serialiser, "
        "defaultValueRef) and to ConditionBuilder.tsx in the same PR."
    )


@pytest.mark.skipif(
    not _CONDITION_EDIT_TS.exists(),
    reason="frontend tree not checked out (backend-only container build)",
)
def test_crop_attribute_source_is_wired_through_the_builder() -> None:
    """Present in the union is not enough — a source the builder cannot parse,
    serialise or default still falls through to the YAML editor."""
    text = _CONDITION_EDIT_TS.read_text(encoding="utf-8")
    assert 'source === "crop_attribute"' in text, "conditionEdit.ts cannot parse the source"
    assert 'case "crop_attribute":' in text, "conditionEdit.ts cannot serialise/default the source"
