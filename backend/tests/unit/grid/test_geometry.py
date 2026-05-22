"""Unit tests for the grid-zones geometry helpers.

The four guardrails in ``validate_cell_size`` and the alignment +
clipping behaviour of ``generate_cells`` are the contract every other
layer of the module relies on. Cover them here so PR-2 (worker hook)
and PR-3 (frontend) can lean on these without re-testing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from shapely.geometry import box

from app.modules.grid.geometry import (
    MAX_CELLS_PER_BLOCK,
    MIN_PIXELS_PER_CELL,
    estimate_cell_count,
    generate_cells,
    validate_cell_size,
)

# ---- validate_cell_size --------------------------------------------------


@pytest.mark.parametrize(
    ("cell_size_m", "native_m", "block_area_m2"),
    [
        # S2 happy path — 20m on 10m native, 10ha block (4 pixels/cell exactly).
        (Decimal("20"), Decimal("10"), Decimal("100000")),
        # Planet-style 9m on 3m native (9 pixels/cell).
        (Decimal("9"), Decimal("3"), Decimal("50000")),
        # Larger multiple — 30m on 10m native (9 pixels/cell).
        (Decimal("30"), Decimal("10"), Decimal("100000")),
    ],
)
def test_validate_cell_size_accepts_well_formed_inputs(
    cell_size_m: Decimal, native_m: Decimal, block_area_m2: Decimal
) -> None:
    assert (
        validate_cell_size(
            cell_size_m=cell_size_m,
            native_pixel_m=native_m,
            block_area_m2=block_area_m2,
        )
        is None
    )


def test_validate_cell_size_rejects_below_native() -> None:
    err = validate_cell_size(
        cell_size_m=Decimal("5"),
        native_pixel_m=Decimal("10"),
        block_area_m2=Decimal("100000"),
    )
    assert err is not None
    assert "below the source's native pixel" in err


def test_validate_cell_size_rejects_non_multiple_of_native() -> None:
    # 15m / 10m = 1.5x — not an integer multiple.
    err = validate_cell_size(
        cell_size_m=Decimal("15"),
        native_pixel_m=Decimal("10"),
        block_area_m2=Decimal("100000"),
    )
    assert err is not None
    assert "integer multiple" in err


def test_validate_cell_size_rejects_too_few_pixels_per_cell() -> None:
    # 10m on 10m native = 1 pixel/cell — below MIN_PIXELS_PER_CELL=4.
    err = validate_cell_size(
        cell_size_m=Decimal("10"),
        native_pixel_m=Decimal("10"),
        block_area_m2=Decimal("100000"),
    )
    assert err is not None
    assert f"≥{MIN_PIXELS_PER_CELL}" in err or "pixels per cell" in err


def test_validate_cell_size_rejects_excessive_cell_count() -> None:
    # 10ha block at 1m cells = 100,000 cells — well over the cap.
    # But 1m < 10m native, so this would fail the native check first.
    # Use a coarser native to isolate the cap check: 100ha block,
    # 20m cells on 10m native = 250_000 cells.
    err = validate_cell_size(
        cell_size_m=Decimal("20"),
        native_pixel_m=Decimal("10"),
        block_area_m2=Decimal(str(MAX_CELLS_PER_BLOCK * 20 * 20 + 1)),
    )
    assert err is not None
    assert str(MAX_CELLS_PER_BLOCK) in err


def test_validate_cell_size_error_order_native_before_multiple() -> None:
    """When two guardrails would trip, the cheaper/more-fundamental one
    wins — keeps the error message actionable."""
    # 5m cell on 10m native is both below native AND not an integer
    # multiple. Native check should fire first.
    err = validate_cell_size(
        cell_size_m=Decimal("5"),
        native_pixel_m=Decimal("10"),
        block_area_m2=Decimal("100000"),
    )
    assert err is not None
    assert "below" in err


# ---- estimate_cell_count -------------------------------------------------


def test_estimate_cell_count_for_aligned_square() -> None:
    # 200m x 200m square at origin, 20m cells = 10x10 = 100 cells.
    poly = box(0, 0, 200, 200)
    assert estimate_cell_count(boundary_utm_wkt=poly.wkt, cell_size_m=Decimal("20")) == 100


def test_estimate_cell_count_rounds_up_partial_cells() -> None:
    # 195m x 195m at origin, 20m cells = ceil(195/20) = 10 each side = 100.
    poly = box(0, 0, 195, 195)
    assert estimate_cell_count(boundary_utm_wkt=poly.wkt, cell_size_m=Decimal("20")) == 100


# ---- generate_cells ------------------------------------------------------


def test_generate_cells_for_aligned_square() -> None:
    # 200m x 200m square anchored at (1000, 2000), 20m cells.
    # Global indices: cols 50..59, rows 100..109.
    poly = box(1000, 2000, 1200, 2200)
    cells = list(generate_cells(boundary_utm_wkt=poly.wkt, cell_size_m=Decimal("20")))
    assert len(cells) == 100
    # Each cell is a full 400 m² (no clipping at edges of an aligned square).
    assert all(abs(c.area_m2 - 400.0) < 1e-6 for c in cells)
    # Indices are *global* (UTM-origin-relative), not 0..9.
    assert {c.col_idx for c in cells} == set(range(50, 60))
    assert {c.row_idx for c in cells} == set(range(100, 110))


def test_generate_cells_assigns_global_indices() -> None:
    """Two blocks containing the same physical cell get the same
    (row_idx, col_idx) for it. This is the V1 design contract that
    makes "cell (123, 45)" a globally meaningful identifier inside a
    UTM zone.

    Block A: [1000..1400, 0..200]
    Block B: [1200..1600, 0..200]    (overlaps A in [1200..1400])

    At 20m cells, the cell at physical x=1200..1220, y=0..20 should
    appear in *both* blocks' outputs with the same (col_idx=60,
    row_idx=0).
    """
    a = box(1000, 0, 1400, 200)
    b = box(1200, 0, 1600, 200)
    a_cells = {(c.row_idx, c.col_idx) for c in generate_cells(
        boundary_utm_wkt=a.wkt, cell_size_m=Decimal("20")
    )}
    b_cells = {(c.row_idx, c.col_idx) for c in generate_cells(
        boundary_utm_wkt=b.wkt, cell_size_m=Decimal("20")
    )}
    # The overlap region [1200..1400, 0..200] = 10 cols x 10 rows = 100 cells.
    overlap = a_cells & b_cells
    assert len(overlap) == 100
    # And the specific cell at x=1200..1220, y=0..20 is in both.
    assert (0, 60) in overlap


def test_generate_cells_clips_to_block_boundary() -> None:
    """A diagonal block boundary should produce cells with partial areas
    along the boundary."""
    # Triangle: (0,0), (200,0), (200,200). Cells along the hypotenuse
    # get clipped to triangles or smaller polygons.
    triangle_wkt = "POLYGON ((0 0, 200 0, 200 200, 0 0))"
    cells = list(generate_cells(boundary_utm_wkt=triangle_wkt, cell_size_m=Decimal("20")))

    # Total clipped area should equal the triangle area exactly
    # (20_000 m² for a right triangle with legs 200).
    total_area = sum(c.area_m2 for c in cells)
    assert abs(total_area - 20_000.0) < 1.0

    # At least one cell got clipped below the full 400 m² (the ones
    # straddling the hypotenuse).
    assert any(c.area_m2 < 400.0 - 1e-6 for c in cells)


def test_generate_cells_empty_for_empty_polygon() -> None:
    cells = list(
        generate_cells(boundary_utm_wkt="POLYGON EMPTY", cell_size_m=Decimal("20"))
    )
    assert cells == []
