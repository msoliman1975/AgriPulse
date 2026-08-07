"""Season context — the crop mix the overview filters by.

The bar used to be read-only labels, so `block_count` was the whole payload.
It is now the page's crop filter, which needs the block ids themselves: the
alternative is one `/blocks/{id}/crop-assignments` call per block, the exact
fan-out that exhausted the pool on the map page.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.insights import service as service_module
from app.modules.insights.service import InsightsService


def _svc() -> InsightsService:
    svc = InsightsService.__new__(InsightsService)
    svc._session = AsyncMock()  # type: ignore[attr-defined]
    svc._farms = AsyncMock()  # type: ignore[attr-defined]
    svc._indices = AsyncMock()  # type: ignore[attr-defined]
    svc._alerts = AsyncMock()  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
class TestSeasonContext:
    async def test_carries_the_blocks_each_crop_is_planted_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        farm_id, mango, palm = uuid4(), uuid4(), uuid4()
        b1, b2, b3 = uuid4(), uuid4(), uuid4()

        svc = _svc()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[{"id": b1}, {"id": b2}, {"id": b3}])  # type: ignore[attr-defined]

        async def fake_select(session: object, *, farm_id: object) -> list[dict[str, object]]:
            return [
                {
                    "crop_id": mango,
                    "name_en": "Mango",
                    "name_ar": "مانجو",
                    "block_count": 2,
                    "block_ids": [b1, b2],
                },
                {
                    "crop_id": palm,
                    "name_en": "Date palm",
                    "name_ar": None,
                    # b2 carries both crops — the counts overlap on purpose,
                    # and the FE unions the id lists rather than summing.
                    "block_count": 2,
                    "block_ids": [b2, b3],
                },
            ]

        monkeypatch.setattr(service_module, "_select_farm_crops", fake_select)

        out = await svc.get_farm_season_context(farm_id=farm_id)

        assert [c.name_en for c in out.crops] == ["Mango", "Date palm"]
        assert out.crops[0].block_ids == [b1, b2]
        assert out.crops[1].block_ids == [b2, b3]
        # The farm has three blocks even though the crop counts sum to four.
        assert out.active_block_count == 3

    async def test_a_crop_with_no_blocks_yields_an_empty_list_not_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        farm_id, crop = uuid4(), uuid4()
        svc = _svc()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        async def fake_select(session: object, *, farm_id: object) -> list[dict[str, object]]:
            # ARRAY_AGG can hand back NULL rather than an empty array; the FE
            # treats null as "no filter", so it must never reach it.
            return [
                {
                    "crop_id": crop,
                    "name_en": "Fallow",
                    "name_ar": None,
                    "block_count": 0,
                    "block_ids": None,
                }
            ]

        monkeypatch.setattr(service_module, "_select_farm_crops", fake_select)

        out = await svc.get_farm_season_context(farm_id=farm_id)
        assert out.crops[0].block_ids == []
