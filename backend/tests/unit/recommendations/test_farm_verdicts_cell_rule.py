"""The farm verdicts read carries each block's rollup rule.

Farm Health colours a block the way block health classes it (Mohamed,
2026-09-28). The page applies the rule itself, because a replay frame is
built in the browser, so the rule has to come from the same tiers block
health reads: platform, tenant, crop, farm. Here the tiers are stubbed and
only the hand-over is checked.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.health.service import CropHealthDefinitions
from app.modules.recommendations.service import RecommendationsServiceImpl


@pytest.mark.asyncio
async def test_each_block_gets_the_rule_of_its_own_crop() -> None:
    mango, bare = uuid4(), uuid4()
    definitions = CropHealthDefinitions(
        {"mango": {"cell_rollup": "share", "cell_critical_share": "0.35"}},
        tenant_tier={"cell_rollup": "most_common"},
    )
    svc = RecommendationsServiceImpl.__new__(RecommendationsServiceImpl)
    svc._tenant = AsyncMock()  # type: ignore[attr-defined]
    with (
        patch(
            "app.modules.health.service.load_health_definitions",
            AsyncMock(return_value=definitions),
        ),
        patch(
            "app.shared.health_evidence.load_crop_paths",
            AsyncMock(return_value={mango: "mango.keitt"}),
        ),
    ):
        rules = await svc._cell_rollup_rules(farm_id=uuid4(), block_ids=[mango, bare])

    # The crop row wins over the tenant, and the share travels as a fraction.
    assert rules[mango] == {"cell_rollup": "share", "cell_share": float(Decimal("0.35"))}
    # No crop: the tenant's rule, and no share, because it is not `share`.
    assert rules[bare] == {"cell_rollup": "most_common", "cell_share": None}
