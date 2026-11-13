"""D18/D23: reference keys, inheritance along the crop path, and the seed."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.reference_values.keys import BY_KEY, plants_per_ha, resolve
from app.modules.reference_values.router import ReferenceValueRequest

_MIG = Path(__file__).parents[3] / "migrations/public/versions/0106_crop_reference_values.py"
_spec = importlib.util.spec_from_file_location("mig0105", _MIG)
assert _spec is not None
assert _spec.loader is not None
MIG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIG)


def _row(path: str, key: str, value: float | None = None, lo=None, hi=None) -> dict:
    return {"crop_path": path, "key": key, "value": value, "value_min": lo, "value_max": hi}


def test_deepest_path_wins_and_says_where_from() -> None:
    rows = [
        _row("date_palm", "row_spacing_m", 10),
        _row("date_palm", "soil_ece_threshold_ds_m", 4.0),
        _row("date_palm.medjool", "row_spacing_m", 9),
        _row("date_palm.barhee", "row_spacing_m", 7),  # a sibling never leaks in
        _row("date_palm.medjool", "not_a_key", 1),  # an unknown key is ignored
    ]
    out = resolve("date_palm.medjool", rows)
    assert out["row_spacing_m"]["value"] == 9
    assert out["row_spacing_m"]["from_path"] == "date_palm.medjool"
    assert out["soil_ece_threshold_ds_m"]["from_path"] == "date_palm"
    assert "not_a_key" not in out


def test_plants_per_ha_follows_from_both_spacings() -> None:
    assert (
        plants_per_ha(
            resolve(
                "date_palm",
                [_row("date_palm", "row_spacing_m", 10), _row("date_palm", "in_row_spacing_m", 8)],
            )
        )
        == 125.0
    )
    assert plants_per_ha(resolve("date_palm", [_row("date_palm", "row_spacing_m", 10)])) is None


def test_request_needs_a_value_or_a_sane_range() -> None:
    with pytest.raises(ValidationError):
        ReferenceValueRequest()
    with pytest.raises(ValidationError):
        ReferenceValueRequest(value_min=Decimal(5), value_max=Decimal(4))
    assert ReferenceValueRequest(value_min=Decimal(60), value_max=Decimal(72)).value is None


def test_seed_uses_known_keys_within_bounds_and_cites_the_manual() -> None:
    for path, key, value, lo, hi, note, refs in MIG.SEED:
        spec = BY_KEY[key]
        for n in (value, lo, hi):
            assert n is None or spec.lower <= n <= spec.upper, (path, key)
        assert note.startswith("Manual 1.7, "), (path, key)
        assert refs, (path, key)
        assert all(c in {"high", "medium", "low", "expert_inference"} for _, c in refs)
