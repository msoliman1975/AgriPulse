"""The daily water-balance sweep, exercised against a fake repository.

The arithmetic is covered in test_water_balance.py; what is tested here is the
wiring the sweep adds on top — phenology resolution per block, the shape of the
rows handed to the upsert, and the query-count discipline that keeps a nightly
sweep from degenerating into per-block round trips.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.irrigation.service import IrrigationServiceImpl

_MANGO = uuid4()
_VARIETY = uuid4()
_DAY = date(2026, 7, 1)


class _FakeRepo:
    """Records calls so the test can assert the sweep's query discipline."""

    def __init__(self, blocks: list[dict[str, Any]], docs: dict[str, dict[UUID, Any]]) -> None:
        self._blocks = blocks
        self._docs = docs
        self.written: list[dict[str, Any]] = []
        self.block_query_count = 0
        self.phenology_query_count = 0

    async def load_water_balance_blocks(self, *, target_date: date) -> list[dict[str, Any]]:
        assert target_date == _DAY
        self.block_query_count += 1
        return self._blocks

    async def load_phenology_by_crop_ids(
        self, *, crop_ids: set[UUID], variety_ids: set[UUID], strain_ids: set[UUID]
    ) -> dict[str, dict[UUID, Any]]:
        self.phenology_query_count += 1
        self.seen_crop_ids = crop_ids
        self.seen_variety_ids = variety_ids
        self.seen_strain_ids = strain_ids
        return self._docs

    async def upsert_water_balance_rows(self, rows: list[dict[str, Any]]) -> int:
        self.written = rows
        return len(rows)


def _service(repo: _FakeRepo) -> IrrigationServiceImpl:
    svc = IrrigationServiceImpl.__new__(IrrigationServiceImpl)
    svc._repo = repo  # type: ignore[attr-defined]
    return svc


def _block(**kw: Any) -> dict[str, Any]:
    base = {
        "block_id": uuid4(),
        "farm_id": uuid4(),
        "crop_id": _MANGO,
        "crop_variety_id": None,
        "crop_variety_strain_id": None,
        "growth_stage": "flowering",
        "et0_mm": Decimal("6.00"),
        "precip_mm": Decimal("0"),
        "irrigation_mm": None,
    }
    return {**base, **kw}


@pytest.mark.asyncio
async def test_writes_one_row_per_block_with_the_full_derivation() -> None:
    repo = _FakeRepo(
        [_block()],
        {
            "crop": {_MANGO: {"stages": [{"code": "flowering", "kc": "0.65"}]}},
            "variety": {},
            "strain": {},
        },
    )
    out = await _service(repo).compute_water_balance_for_day(target_date=_DAY)

    assert out == {"blocks": 1, "rows_written": 1}
    row = repo.written[0]
    # ETc = 0.65 * 6.00, balance = 0 + 0 - 3.90.
    assert row["etc_mm"] == Decimal("3.90")
    assert row["balance_mm"] == Decimal("-3.90")
    # The derivation is persisted alongside the answer, not just the answer.
    assert row["kc_used"] == Decimal("0.65")
    assert row["kc_source"] == "phenology"
    assert row["et0_mm"] == Decimal("6.00")
    assert row["growth_stage"] == "flowering"
    assert row["date"] == _DAY


@pytest.mark.asyncio
async def test_variety_phenology_overrides_the_crop_curve() -> None:
    repo = _FakeRepo(
        [_block(crop_variety_id=_VARIETY)],
        {
            "crop": {_MANGO: {"stages": [{"code": "flowering", "kc": "0.65"}]}},
            "variety": {_VARIETY: {"stages": [{"code": "flowering", "kc": "0.95"}]}},
            "strain": {},
        },
    )
    await _service(repo).compute_water_balance_for_day(target_date=_DAY)
    assert repo.written[0]["kc_used"] == Decimal("0.95")


@pytest.mark.asyncio
async def test_logged_irrigation_turns_a_deficit_into_a_surplus() -> None:
    repo = _FakeRepo(
        [_block(irrigation_mm=Decimal("8.00"), growth_stage=None)],
        {"crop": {}, "variety": {}, "strain": {}},
    )
    await _service(repo).compute_water_balance_for_day(target_date=_DAY)
    row = repo.written[0]
    # No phenology and no stage → generic 0.85 fallback → ETc 5.10.
    assert row["kc_source"] == "generic_default"
    assert row["balance_mm"] == Decimal("2.90")
    assert row["irrigation_logged"] is True


@pytest.mark.asyncio
async def test_query_count_is_flat_in_the_number_of_blocks() -> None:
    """The point of the set-based path: 200 blocks cost the same round trips
    as one. Looping the per-block recommendation helper would have issued four
    queries each."""
    blocks = [_block() for _ in range(200)]
    repo = _FakeRepo(blocks, {"crop": {}, "variety": {}, "strain": {}})
    out = await _service(repo).compute_water_balance_for_day(target_date=_DAY)

    assert out["rows_written"] == 200
    assert repo.block_query_count == 1
    assert repo.phenology_query_count == 1


@pytest.mark.asyncio
async def test_only_referenced_catalog_ids_are_looked_up() -> None:
    repo = _FakeRepo(
        [_block(), _block(crop_variety_id=_VARIETY)],
        {"crop": {}, "variety": {}, "strain": {}},
    )
    await _service(repo).compute_water_balance_for_day(target_date=_DAY)
    assert repo.seen_crop_ids == {_MANGO}
    assert repo.seen_variety_ids == {_VARIETY}
    # No block references a strain, so the sweep must not ask for any — an
    # empty `IN ()` is a syntax error, not an empty result.
    assert repo.seen_strain_ids == set()


@pytest.mark.asyncio
async def test_a_day_with_no_eligible_blocks_writes_nothing() -> None:
    """Not an error: a tenant may have no blocks with both a crop and ET₀."""
    repo = _FakeRepo([], {"crop": {}, "variety": {}, "strain": {}})
    out = await _service(repo).compute_water_balance_for_day(target_date=_DAY)
    assert out == {"blocks": 0, "rows_written": 0}
    assert repo.written == []
    # And it must not pay for the phenology lookups either.
    assert repo.phenology_query_count == 0
