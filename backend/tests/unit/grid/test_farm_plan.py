"""Decision-table tests for the farm-wide threshold plan.

Pure — no DB. Each test pins one branch of ``plan_threshold_row`` so a
regression names the exact case it broke.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.grid.farm_plan import (
    GridRowState,
    plan_threshold,
    plan_threshold_row,
    summarize,
)


def _state(
    *,
    with_subscription: bool = True,
    with_grid: bool = True,
    current_z: Decimal | None = None,
    cell_size: Decimal | None = Decimal("20.00"),
) -> GridRowState:
    return GridRowState(
        block_id=uuid4(),
        block_code="A-01",
        block_name="North Mango 1",
        product_id=uuid4() if with_subscription else None,
        product_code="s2_l2a" if with_subscription else None,
        product_name="Sentinel-2 L2A" if with_subscription else None,
        native_pixel_m=Decimal("10.00") if with_subscription else None,
        grid_config_id=uuid4() if (with_subscription and with_grid) else None,
        current_cell_size_m=cell_size if (with_subscription and with_grid) else None,
        current_anomaly_z_threshold=current_z,
    )


# ---- skip branches ---------------------------------------------------------


def test_block_without_subscription_is_skipped() -> None:
    row = plan_threshold_row(
        _state(with_subscription=False),
        template_z=Decimal("1.20"),
        clear_override=False,
    )
    assert row.action == "skipped"
    assert "subscription" in row.reason.lower()
    assert not row.is_change


def test_block_without_grid_is_skipped_and_says_why() -> None:
    """The ordering dependency from the UX: no grid, no threshold."""
    row = plan_threshold_row(
        _state(with_grid=False),
        template_z=Decimal("1.20"),
        clear_override=False,
    )
    assert row.action == "skipped"
    assert "cell size" in row.reason.lower()


# ---- normal apply ----------------------------------------------------------


def test_sets_threshold_when_block_differs() -> None:
    row = plan_threshold_row(
        _state(current_z=Decimal("1.50")),
        template_z=Decimal("1.20"),
        clear_override=False,
    )
    assert row.action == "threshold"
    assert row.target_anomaly_z_threshold == Decimal("1.20")
    assert row.is_change


def test_sets_threshold_when_block_has_no_override_yet() -> None:
    row = plan_threshold_row(
        _state(current_z=None),
        template_z=Decimal("1.20"),
        clear_override=False,
    )
    assert row.action == "threshold"
    assert row.target_anomaly_z_threshold == Decimal("1.20")


def test_matching_block_is_no_change() -> None:
    row = plan_threshold_row(
        _state(current_z=Decimal("1.20")),
        template_z=Decimal("1.20"),
        clear_override=False,
    )
    assert row.action == "none"
    assert not row.is_change


def test_trailing_zero_scale_is_not_a_spurious_change() -> None:
    """farms NUMERIC(4,2) vs grid_configs NUMERIC(4,2) round-trips.

    Decimal("1.5") and Decimal("1.50") compare equal; if this ever
    switched to string comparison every block would look divergent and
    Apply would rewrite the whole farm on every run.
    """
    row = plan_threshold_row(
        _state(current_z=Decimal("1.5")),
        template_z=Decimal("1.50"),
        clear_override=False,
    )
    assert row.action == "none"


def test_empty_template_is_reported_not_silently_matched() -> None:
    """#330's failure mode: a no-op must explain itself."""
    row = plan_threshold_row(
        _state(current_z=Decimal("1.50")),
        template_z=None,
        clear_override=False,
    )
    assert row.action == "none"
    assert "no farm template" in row.reason.lower()


# ---- clear_override --------------------------------------------------------


def test_clear_override_removes_a_pinned_value() -> None:
    row = plan_threshold_row(
        _state(current_z=Decimal("1.20")),
        template_z=Decimal("9.99"),  # ignored on this path
        clear_override=True,
    )
    assert row.action == "threshold"
    assert row.target_anomaly_z_threshold is None
    assert "inherit" in row.reason.lower()


def test_clear_override_is_a_noop_when_already_inheriting() -> None:
    row = plan_threshold_row(
        _state(current_z=None),
        template_z=Decimal("1.20"),
        clear_override=True,
    )
    assert row.action == "none"


def test_clear_override_ignores_the_template_value() -> None:
    """Otherwise "clear" would quietly become "set to the template"."""
    row = plan_threshold_row(
        _state(current_z=Decimal("2.00")),
        template_z=Decimal("1.20"),
        clear_override=True,
    )
    assert row.target_anomaly_z_threshold is None


# ---- summary ---------------------------------------------------------------


def test_summary_counts_each_bucket() -> None:
    states = (
        _state(current_z=Decimal("1.50")),  # -> threshold
        _state(current_z=Decimal("1.20")),  # -> none
        _state(with_grid=False),  # -> skipped
        _state(with_subscription=False),  # -> skipped
    )
    rows = plan_threshold(states, template_z=Decimal("1.20"), clear_override=False)
    s = summarize(rows)
    assert (s.total_rows, s.changed_rows, s.unchanged_rows, s.skipped_rows) == (4, 1, 1, 2)
    assert not s.is_noop


def test_summary_is_noop_when_nothing_changes() -> None:
    """Drives the disabled Confirm button and the warning-not-green result."""
    states = (
        _state(current_z=Decimal("1.20")),
        _state(with_grid=False),
    )
    rows = plan_threshold(states, template_z=Decimal("1.20"), clear_override=False)
    assert summarize(rows).is_noop
