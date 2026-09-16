"""The refusal to discard a version says which rule held it.

`discard_version` refuses four things, and they are not the same problem: a
published version is history, the current version is what the engine reads, the
only version is all the editor has, and a pinned version has tenants following
it. The status and the `reason` are what the UI puts next to the button, so
they are asserted here rather than left to whatever the router happened to do.

409, not 403: the caller may edit this tree. This one version is the thing they
cannot remove. DB-less — this covers the mapping, not the guards, which
`tests/integration/recommendations/test_discard_draft_version.py` covers.
"""

from __future__ import annotations

import pytest

from app.modules.recommendations.router import _map_authoring_error
from app.modules.recommendations.service import _DecisionTreeVersionNotDiscardableError

_REASONS = ["published", "current", "only_version", "pinned"]


@pytest.mark.parametrize("reason", _REASONS)
def test_maps_to_409_carrying_the_reason(reason: str) -> None:
    mapped = _map_authoring_error(
        _DecisionTreeVersionNotDiscardableError(
            code="potato_frost_risk_v1", version=6, reason=reason, detail="because."
        )
    )
    assert mapped is not None
    assert mapped.status_code == 409
    assert mapped.extras == {"code": "potato_frost_risk_v1", "version": 6, "reason": reason}


def test_the_detail_is_the_sentence_the_service_wrote() -> None:
    # Not a restatement built in the router: the service knows which rule ran,
    # and the author reads that sentence.
    mapped = _map_authoring_error(
        _DecisionTreeVersionNotDiscardableError(
            code="t",
            version=2,
            reason="pinned",
            detail="Version 2 of 't' is pinned by 3 tenant(s).",
        )
    )
    assert mapped is not None
    assert mapped.detail == "Version 2 of 't' is pinned by 3 tenant(s)."
