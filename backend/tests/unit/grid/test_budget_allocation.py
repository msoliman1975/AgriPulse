"""Fair-share allocation of a farm-wide backfill budget.

Pure — no DB. The property that matters is that one enormous block cannot
starve the rest of the farm, because the per-block cap this replaces did
exactly that at farm scale.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.grid.backfill import allocate_budget


def _jobs(n: int, prefix: str) -> list[dict[str, str]]:
    """Newest-first, like ``list_backfill_jobs`` returns."""
    return [
        {"job_id": f"{prefix}-{i}", "scene_datetime": f"2026-01-{i + 1:02d}", "raw_bands_key": "k"}
        for i in range(n)
    ]


def test_no_budget_means_everything() -> None:
    a, b = uuid4(), uuid4()
    pairs = {(a, a): _jobs(500, "a"), (b, b): _jobs(3, "b")}
    allocated, stranded = allocate_budget(pairs, budget=None)
    assert sum(len(v) for v in allocated.values()) == 503
    assert stranded == 0


def test_one_huge_block_cannot_starve_the_farm() -> None:
    """The failure the per-block cap produced: 1 block eats the budget."""
    big, small1, small2 = uuid4(), uuid4(), uuid4()
    pairs = {
        (big, big): _jobs(500, "big"),
        (small1, small1): _jobs(4, "s1"),
        (small2, small2): _jobs(4, "s2"),
    }
    allocated, stranded = allocate_budget(pairs, budget=12)

    assert sum(len(v) for v in allocated.values()) == 12
    assert stranded == 500 + 4 + 4 - 12
    # Every pair got something, and the small ones got fully served.
    assert len(allocated[(small1, small1)]) == 4
    assert len(allocated[(small2, small2)]) == 4
    assert len(allocated[(big, big)]) == 4


def test_leftover_budget_flows_to_whoever_still_has_scenes() -> None:
    """Once small queues drain, the remainder goes to the big one."""
    big, small = uuid4(), uuid4()
    pairs = {(big, big): _jobs(100, "big"), (small, small): _jobs(2, "s")}
    allocated, stranded = allocate_budget(pairs, budget=20)

    assert len(allocated[(small, small)]) == 2
    assert len(allocated[(big, big)]) == 18
    assert stranded == 82


def test_newest_scenes_are_taken_first() -> None:
    """Settle walks effective_from backwards; it needs newest-first order."""
    a = uuid4()
    allocated, _ = allocate_budget({(a, a): _jobs(10, "a")}, budget=3)
    assert [j["job_id"] for j in allocated[(a, a)]] == ["a-0", "a-1", "a-2"]


def test_budget_larger_than_available_strands_nothing() -> None:
    a = uuid4()
    allocated, stranded = allocate_budget({(a, a): _jobs(5, "a")}, budget=99)
    assert len(allocated[(a, a)]) == 5
    assert stranded == 0


def test_zero_budget_takes_nothing_and_reports_it() -> None:
    """Silent truncation reads as 'covered everything'. It must not."""
    a = uuid4()
    allocated, stranded = allocate_budget({(a, a): _jobs(7, "a")}, budget=0)
    assert allocated[(a, a)] == []
    assert stranded == 7


def test_empty_farm_is_not_an_error() -> None:
    allocated, stranded = allocate_budget({}, budget=10)
    assert allocated == {}
    assert stranded == 0
