"""Decision-table tests for the farm-wide cell-size plan.

Pure — no DB. The interesting cases are the guardrails, because the
original UX mock implemented only two of ``validate_cell_size``'s four
rules and therefore showed sizes as valid that the backend rejects. These
tests pin all four running through the real function, per (block, product).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.grid.farm_plan import (
    GridRowState,
    plan_cell_size,
    plan_cell_size_row,
    summarize,
)

# A 40 ha block: big enough that 20 m is comfortably under the 5000-cell
# ceiling, small enough that a fine cell size breaches it.
_AREA_40HA = Decimal("400000")


def _state(
    *,
    native_pixel: Decimal | None = Decimal("10.00"),
    current_cell_size: Decimal | None = Decimal("20.00"),
    with_subscription: bool = True,
    with_grid: bool = True,
    area_m2: Decimal | None = _AREA_40HA,
    scenes: int = 0,
) -> GridRowState:
    return GridRowState(
        block_id=uuid4(),
        block_code="A-01",
        block_name="North Mango 1",
        product_id=uuid4() if with_subscription else None,
        product_code="s2_l2a" if with_subscription else None,
        product_name="Sentinel-2 L2A" if with_subscription else None,
        native_pixel_m=native_pixel if with_subscription else None,
        grid_config_id=uuid4() if (with_subscription and with_grid) else None,
        current_cell_size_m=current_cell_size if (with_subscription and with_grid) else None,
        current_anomaly_z_threshold=None,
        block_area_m2=area_m2,
        scenes_affected=scenes,
    )


# ---- skip / no-op branches -------------------------------------------------


def test_block_without_subscription_is_skipped() -> None:
    row = plan_cell_size_row(_state(with_subscription=False), template_cell_size=Decimal("20"))
    assert row.action == "skipped"
    assert "subscription" in row.reason.lower()
    assert not row.is_change


def test_empty_template_writes_nothing() -> None:
    """An unset template is reported, not silently treated as a match.

    "0 blocks changed" with no explanation is the #330 failure mode.
    """
    row = plan_cell_size_row(_state(), template_cell_size=None)
    assert row.action == "none"
    assert "No farm template" in row.reason
    assert not row.is_change


def test_matching_cell_size_is_not_a_change() -> None:
    row = plan_cell_size_row(
        _state(current_cell_size=Decimal("20")), template_cell_size=Decimal("20")
    )
    assert row.action == "none"
    assert not row.is_change
    assert not row.is_destructive


def test_scale_difference_is_not_a_change() -> None:
    """NUMERIC(6,2) round-trips 20 as 20.00; that must not read as a rezone."""
    row = plan_cell_size_row(
        _state(current_cell_size=Decimal("20.00")), template_cell_size=Decimal("20")
    )
    assert row.action == "none"


# ---- the four guardrails ---------------------------------------------------


def test_below_native_pixel_is_blocked() -> None:
    row = plan_cell_size_row(_state(native_pixel=Decimal("10")), template_cell_size=Decimal("5"))
    assert row.action == "blocked"
    assert not row.is_change
    assert "native pixel" in row.reason


def test_non_integer_multiple_is_blocked() -> None:
    """25 m on a 10 m source. The UX mock showed this as PASSING."""
    row = plan_cell_size_row(_state(native_pixel=Decimal("10")), template_cell_size=Decimal("25"))
    assert row.action == "blocked"
    assert "integer multiple" in row.reason


def test_too_few_pixels_per_cell_is_blocked() -> None:
    row = plan_cell_size_row(_state(native_pixel=Decimal("10")), template_cell_size=Decimal("10"))
    assert row.action == "blocked"
    assert "pixels per cell" in row.reason


def test_cell_ceiling_depends_on_the_blocks_own_area() -> None:
    """Rule 4 is why a per-product floor table cannot drive the preview.

    Same product, same cell size, different blocks — one passes, one is
    blocked. No farm-level table can express that.
    """
    small = plan_cell_size_row(
        _state(native_pixel=Decimal("3"), area_m2=Decimal("100000")),
        template_cell_size=Decimal("12"),
    )
    huge = plan_cell_size_row(
        _state(native_pixel=Decimal("3"), area_m2=Decimal("900000000")),
        template_cell_size=Decimal("12"),
    )
    assert small.action != "blocked"
    assert huge.action == "blocked"
    assert "cap" in huge.reason


def test_one_size_passes_some_products_and_fails_others() -> None:
    """8 m: fine for PlanetScope (3 m px), impossible for Sentinel-2 (10 m)."""
    planet = plan_cell_size_row(
        _state(native_pixel=Decimal("3"), current_cell_size=Decimal("30")),
        template_cell_size=Decimal("12"),
    )
    s2 = plan_cell_size_row(
        _state(native_pixel=Decimal("10"), current_cell_size=Decimal("30")),
        template_cell_size=Decimal("12"),
    )
    assert planet.action == "rezone"
    assert s2.action == "blocked"


# ---- create vs rezone ------------------------------------------------------


def test_block_without_a_grid_is_a_create_not_a_rezone() -> None:
    """A create destroys nothing, so it must not demand the destructive confirm."""
    row = plan_cell_size_row(_state(with_grid=False), template_cell_size=Decimal("20"))
    assert row.action == "create"
    assert row.is_change
    assert not row.is_destructive
    assert row.target_cell_size_m == Decimal("20")


def test_changing_cell_size_is_a_destructive_rezone() -> None:
    row = plan_cell_size_row(
        _state(current_cell_size=Decimal("30")), template_cell_size=Decimal("20")
    )
    assert row.action == "rezone"
    assert row.is_change
    assert row.is_destructive
    assert row.target_cell_size_m == Decimal("20")
    assert "30m → 20m" in row.reason


# ---- summary ---------------------------------------------------------------


def test_summary_counts_each_action_and_only_strands_rezone_scenes() -> None:
    rows = plan_cell_size(
        (
            _state(current_cell_size=Decimal("30"), scenes=214),  # rezone
            _state(with_grid=False, scenes=0),  # create
            _state(current_cell_size=Decimal("20"), scenes=99),  # none
            _state(with_subscription=False),  # skipped
            _state(native_pixel=Decimal("10"), current_cell_size=Decimal("30")),  # ok
        ),
        template_cell_size=Decimal("20"),
    )
    s = summarize(rows)
    assert s.total_rows == 5
    assert s.rezone_rows == 2
    assert s.create_rows == 1
    assert s.unchanged_rows == 1
    assert s.skipped_rows == 1
    assert s.changed_rows == 3
    assert s.has_destructive
    # Only the rezoned row carried history; the unchanged row's 99 scenes
    # are not at risk and must not inflate the warning.
    assert s.scenes_affected == 214


def test_blocked_rows_are_not_counted_as_changes() -> None:
    """A preview that counts refusals as work promises what it won't do."""
    rows = plan_cell_size(
        (_state(native_pixel=Decimal("10")), _state(native_pixel=Decimal("10"))),
        template_cell_size=Decimal("25"),
    )
    s = summarize(rows)
    assert s.blocked_rows == 2
    assert s.changed_rows == 0
    assert not s.has_destructive


def test_create_only_plan_is_not_destructive() -> None:
    rows = plan_cell_size(
        (_state(with_grid=False), _state(with_grid=False)),
        template_cell_size=Decimal("20"),
    )
    s = summarize(rows)
    assert s.create_rows == 2
    assert s.changed_rows == 2
    assert not s.has_destructive
    assert s.scenes_affected == 0
