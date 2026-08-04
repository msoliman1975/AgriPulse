"""Pure planning for farm-wide grid config applies.

Given the current state of every ``(block, active imagery subscription)``
pair under a farm plus the farm's template, decide what Apply would do to
each — with no DB access, so the decision table is unit-testable on its
own.

Two scopes are planned here, and they are deliberately separate:

* **threshold** — non-destructive. Writes ``anomaly_z_threshold`` in
  place on an already-active config.
* **cell size** — destructive. Retires a geometry and regenerates its
  cells, which is only safe now that grid configs carry valid time
  (tenant migration 0054).

They are numbered in the UI for a load-bearing reason: a block with no
grid cannot take a threshold, so ① cell size gates ②.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.modules.grid.geometry import validate_cell_size

# Deliberately mirrors the vocabulary the preview UI renders as badges.
GridRowAction = Literal["threshold", "rezone", "create", "blocked", "none", "skipped"]

# Actions that write something. ``blocked`` is NOT a change — it is a
# refusal, and counting it as one is how a preview ends up promising work
# it will not do.
_WRITING_ACTIONS = ("threshold", "rezone", "create")


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
    # Needed for guardrail #4 (the ≤5000-cells-per-block ceiling), which
    # is why a farm-wide cell size cannot be validated from a per-product
    # floor table: two blocks on the same product can disagree.
    block_area_m2: Decimal | None = None
    # Rows already recorded against this block+product, used to state the
    # cost of a rezone honestly. Populated by the service, not planned.
    scenes_affected: int = 0


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
    # For action="rezone"/"create": the geometry Apply would build.
    target_cell_size_m: Decimal | None = None

    @property
    def is_change(self) -> bool:
        return self.action in _WRITING_ACTIONS

    @property
    def is_destructive(self) -> bool:
        """True only for a rezone — the case that retires live geometry.

        ``create`` builds a grid where none existed, so it destroys
        nothing; the UI must not demand a type-the-farm-name confirmation
        for a farm whose blocks are simply being gridded for the first
        time, or the confirmation stops meaning anything.
        """
        return self.action == "rezone"


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


def _cell_size_precheck(
    state: GridRowState, template_cell_size: Decimal | None
) -> GridPlanRow | None:
    """Reasons this row can't be planned at all, or None to continue."""
    if state.product_id is None:
        return GridPlanRow(state=state, action="skipped", reason="No active imagery subscription")
    if template_cell_size is None:
        return GridPlanRow(state=state, action="none", reason="No farm template set")
    if state.native_pixel_m is None:
        return GridPlanRow(
            state=state, action="skipped", reason="Product has no known native pixel size"
        )
    return None


def plan_cell_size_row(
    state: GridRowState,
    *,
    template_cell_size: Decimal | None,
) -> GridPlanRow:
    """Decide what a cell-size Apply does to one row.

    The guardrail is the **real** ``validate_cell_size``, run per
    ``(block, product)``, not a client-side approximation. Two of its four
    rules cannot be evaluated any other way: "integer multiple of the
    native pixel" depends on the product, and the ≤5000-cell ceiling
    depends on the block's own area. A farm-wide input of 8 m passes for
    PlanetScope and fails for every Sentinel-2 block in the same farm, and
    the preview has to say so per row.
    """
    precheck = _cell_size_precheck(state, template_cell_size)
    if precheck is not None:
        return precheck
    # Narrowed by the precheck above.
    assert template_cell_size is not None
    assert state.native_pixel_m is not None

    error = validate_cell_size(
        cell_size_m=template_cell_size,
        native_pixel_m=state.native_pixel_m,
        block_area_m2=state.block_area_m2 or Decimal(0),
    )
    if error is not None:
        # Carries the backend's own wording verbatim. The operator needs
        # the reason this block refused, not a generic "invalid".
        return GridPlanRow(state=state, action="blocked", reason=error)

    if state.grid_config_id is None:
        return GridPlanRow(
            state=state,
            action="create",
            reason="No grid yet — one will be created",
            target_cell_size_m=template_cell_size,
        )

    if state.current_cell_size_m == template_cell_size:
        return GridPlanRow(state=state, action="none", reason="Already matches the farm template")

    return GridPlanRow(
        state=state,
        action="rezone",
        reason=(
            f"Rezone {state.current_cell_size_m:g}m → {template_cell_size:g}m"
            if state.current_cell_size_m is not None
            else "Rezone"
        ),
        target_cell_size_m=template_cell_size,
    )


def plan_cell_size(
    states: tuple[GridRowState, ...],
    *,
    template_cell_size: Decimal | None,
) -> tuple[GridPlanRow, ...]:
    return tuple(plan_cell_size_row(s, template_cell_size=template_cell_size) for s in states)


@dataclass(frozen=True, slots=True)
class GridPlanSummary:
    """Counts the preview footer renders. Derived, never stored."""

    total_rows: int
    changed_rows: int
    unchanged_rows: int
    skipped_rows: int
    rezone_rows: int = 0
    create_rows: int = 0
    blocked_rows: int = 0
    scenes_affected: int = 0

    @property
    def has_destructive(self) -> bool:
        """Whether Apply would retire live geometry.

        Drives the type-the-farm-name confirmation. Keyed on rezones only
        — see ``GridPlanRow.is_destructive``.
        """
        return self.rezone_rows > 0

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
        changed_rows=sum(1 for r in rows if r.is_change),
        unchanged_rows=sum(1 for r in rows if r.action == "none"),
        skipped_rows=sum(1 for r in rows if r.action == "skipped"),
        rezone_rows=sum(1 for r in rows if r.action == "rezone"),
        create_rows=sum(1 for r in rows if r.action == "create"),
        blocked_rows=sum(1 for r in rows if r.action == "blocked"),
        # Only rezones strand history — a create has none to strand.
        scenes_affected=sum(r.state.scenes_affected for r in rows if r.action == "rezone"),
    )
