"""The beta dry run's block picker: every block, each with the sweep's verdict.

The picker used to list the caller's blocks with no regard for the tree, so a
block with no country or crop folded under an EG-only palm tree and read as if
production would run the tree there. Each row now says whether it would.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.recommendations import folding_authoring
from app.modules.recommendations.folding_authoring import (
    BetaDryRunUnavailableError,
    FoldingTreeAuthorService,
)


def _block(name: str, *, country: str | None, crop: str | None) -> dict[str, Any]:
    return {
        "block_id": uuid4(),
        "block_name": name,
        "block_name_ar": None,
        "block_code": name.upper(),
        "soil_texture": None,
        "farm_id": uuid4(),
        "farm_name": "Farm",
        "farm_name_ar": "مزرعة",
        "country_code": country,
        "crop_id": None,
        "crop_path": crop,
    }


BLOCKS = [
    _block("bare", country=None, crop=None),
    _block("eg_palm", country="EG", crop="date_palm.medjool"),
    _block("sa_palm", country="SA", crop="date_palm"),
]


def _service(
    monkeypatch: pytest.MonkeyPatch, compiled: dict[str, Any] | None
) -> FoldingTreeAuthorService:
    service = FoldingTreeAuthorService.__new__(FoldingTreeAuthorService)
    service._public = None  # type: ignore[assignment]

    async def resolve(**_: Any) -> Any:
        if compiled is None:
            raise BetaDryRunUnavailableError("This tree has no version to run.")
        return {"code": "t"}, compiled, uuid4()

    class _Repo:
        def __init__(self, **_: Any) -> None:
            pass

        async def list_blocks_for_targeting(self) -> list[dict[str, Any]]:
            return [dict(b) for b in BLOCKS]

    monkeypatch.setattr(service, "_resolve_run_body", resolve, raising=False)
    monkeypatch.setattr(folding_authoring, "RecommendationsRepository", _Repo)
    return service


async def test_rows_carry_the_verdict_and_targeted_blocks_come_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(monkeypatch, {"crop_paths": ["date_palm"], "country_codes": ["EG"]})
    rows = await service.dry_run_blocks(tree_id=uuid4(), tenant_session=None)  # type: ignore[arg-type]

    by_label = {r["label"]: r for r in rows}
    assert rows[0]["label"] == "Farm / eg_palm", "the one targeted block is listed first"
    assert by_label["Farm / eg_palm"]["targeting"]["matched"] is True

    # No crop and no country: rejected on crop, the first axis checked.
    bare = by_label["Farm / bare"]["targeting"]
    assert bare == {"matched": False, "axis": "crop", "required": ["date_palm"], "actual": None}

    sa = by_label["Farm / sa_palm"]["targeting"]
    assert sa["matched"] is False
    assert sa["axis"] == "country"
    assert sa["required"] == ["EG"]
    assert sa["actual"] == "SA"

    # Untargeted blocks stay listed so an author can fold one on purpose.
    assert len(rows) == len(BLOCKS)
    assert by_label["Farm / bare"]["label_ar"] == "مزرعة / bare"


async def test_a_tree_with_no_version_lists_blocks_without_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(monkeypatch, None)
    rows = await service.dry_run_blocks(tree_id=uuid4(), tenant_session=None)  # type: ignore[arg-type]
    assert [r["label"] for r in rows] == ["Farm / bare", "Farm / eg_palm", "Farm / sa_palm"]
    assert all(r["targeting"] is None for r in rows)
