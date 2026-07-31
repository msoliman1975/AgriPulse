"""Pure planning for farm-wide grid config applies.

Given the current state of every ``(block, active imagery subscription)``
pair under a farm plus the farm's template, decide what Apply would do to
each — with no DB access, so the decision table is unit-testable on its
own.

Scope note: this module currently plans the **anomaly threshold** only.
Cell-size planning (rezone / create / blocked, gated on
``geometry.validate_cell_size``) lands with the bulk-rezone work once
grid configs carry valid time — see
``docs/proposals/bulk-grid-config-and-valid-time.md``. The row carries
``current_cell_size_m`` already because "has no grid yet" is exactly why
a block can't take a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

# Deliberately mirrors the vocabulary the preview UI renders as badges.
# ``rezone`` / ``create`` / ``blocked`` are reserved for the cell-size
# scope and are not produced here.
GridRowAction = Literal["threshold", "none", "skipped"]


@dataclass(frozen=True, slots=True)
class GridRowState:
    """Current state of one (block, active subscription) pair.

    A block with no active imagery subscription still produces one row
    with ``product_id is None`` — it appears in the preview as skipped
    rather than vanishing, so the operator can see why it was left out.
    """

    block_id: UUID
    block_code: str
    block_name: str | None
    product_id: UUID | None
    product_code: str | None
    product_name: str | None
    native_pixel_m: Decimal | None
    grid_config_id: UUID | None
    current_cell_size_m: Decimal | None
    current_anomaly_z_threshold: Decimal | None


@dataclass(frozen=True, slots=True)
class GridPlanRow:
    """What Apply would do to one row, and why."""

    state: GridRowState
    action: GridRowAction
    reason: str
    # The value Apply would write. None is meaningful in two different
    # ways: for action="threshold" it means "clear the override so the
    # block inherits the tenant default"; for action="none"/"skipped"
    # nothing is written at all.
    target_anomaly_z_threshold: Decimal | None = None

    @property
    def is_change(self) -> bool:
        return self.action == "threshold"


def _skip_reason(state: GridRowState) -> str | None:
    """Why this row can't take a threshold at all, or None if it can."""
    if state.product_id is None:
        return "No active imagery subscription"
    if state.grid_config_id is None:
        return "No grid yet — set a cell size for this block first"
    return None


def plan_threshold_row(
    state: GridRowState,
    *,
    template_z: Decimal | None,
    clear_override: bool,
) -> GridPlanRow:
    """Decide what a threshold Apply does to one row.

    ``clear_override=True`` means "write NULL", i.e. detach the block
    from its own override and let it inherit tenant → platform again.
    That is the escape hatch from what is otherwise a one-way door:
    applying a farm threshold pins every block, and without this they
    would never follow a later tenant-level change.
    """
    skip = _skip_reason(state)
    if skip is not None:
        return GridPlanRow(state=state, action="skipped", reason=skip)

    current = state.current_anomaly_z_threshold

    if clear_override:
        if current is None:
            return GridPlanRow(
                state=state,
                action="none",
                reason="Already inheriting the tenant default",
            )
        return GridPlanRow(
            state=state,
            action="threshold",
            reason="Clear override — inherit the tenant default",
            target_anomaly_z_threshold=None,
        )

    if template_z is None:
        # Empty template: nothing to copy. Reported rather than silently
        # treated as a match, because "0 blocks changed" with no
        # explanation is the #330 failure mode.
        return GridPlanRow(
            state=state,
            action="none",
            reason="No farm template set",
        )

    # Decimal("1.50") == Decimal("1.5") is True, so trailing-zero scale
    # differences between the farm column NUMERIC(4,2) and the block
    # column don't register as spurious changes.
    if current is not None and current == template_z:
        return GridPlanRow(
            state=state,
            action="none",
            reason="Already matches the farm template",
        )

    return GridPlanRow(
        state=state,
        action="threshold",
        reason="Set from the farm template",
        target_anomaly_z_threshold=template_z,
    )


def plan_threshold(
    states: tuple[GridRowState, ...],
    *,
    template_z: Decimal | None,
    clear_override: bool,
) -> tuple[GridPlanRow, ...]:
    return tuple(
        plan_threshold_row(s, template_z=template_z, clear_override=clear_override) for s in states
    )


@dataclass(frozen=True, slots=True)
class GridPlanSummary:
    """Counts the preview footer renders. Derived, never stored."""

    total_rows: int
    changed_rows: int
    unchanged_rows: int
    skipped_rows: int

    @property
    def is_noop(self) -> bool:
        """True when Apply would write nothing.

        The UI uses this to disable Confirm and to render the result as a
        warning rather than a green success — the #330 guard.
        """
        return self.changed_rows == 0


def summarize(rows: tuple[GridPlanRow, ...]) -> GridPlanSummary:
    return GridPlanSummary(
        total_rows=len(rows),
        changed_rows=sum(1 for r in rows if r.action == "threshold"),
        unchanged_rows=sum(1 for r in rows if r.action == "none"),
        skipped_rows=sum(1 for r in rows if r.action == "skipped"),
    )
