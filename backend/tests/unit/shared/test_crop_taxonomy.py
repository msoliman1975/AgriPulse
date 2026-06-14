"""Pure-function tests for crop-taxonomy path helpers."""

from __future__ import annotations

import pytest

from app.shared.crop_taxonomy import path_matches, strain_code


@pytest.mark.parametrize(
    ("target", "actual", "expected"),
    [
        # Whole-crop target matches every descendant.
        ("mango", "mango.alphonso.short", True),
        ("mango", "mango.alphonso", True),
        ("mango", "mango", True),
        # Variety target matches its strains, exact match included.
        ("mango.alphonso", "mango.alphonso.short", True),
        ("mango.alphonso", "mango.alphonso", True),
        # Sibling variety / crop does not match.
        ("mango.alphonso", "mango.eswwy.long", False),
        ("mango", "cotton", False),
        # Must break on a segment boundary, not a raw string prefix.
        ("mango.alph", "mango.alphonso", False),
        # Empty/None target = no constraint (matches anything).
        (None, "mango.alphonso", True),
        ("", "cotton", True),
        # A block with no path only matches the empty target.
        ("mango", None, False),
        (None, None, True),
    ],
)
def test_path_matches(target: str | None, actual: str | None, expected: bool) -> None:
    assert path_matches(target, actual) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("mango.alphonso.short", "short"),
        ("mango.alphonso", None),
        ("cotton", None),
        ("", None),
        (None, None),
    ],
)
def test_strain_code(path: str | None, expected: str | None) -> None:
    assert strain_code(path) == expected
