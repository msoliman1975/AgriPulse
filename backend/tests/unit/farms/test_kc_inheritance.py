"""Kc inheritance through phenology overrides (decision D19).

A variety (or strain) calendar replaces the crop's stage list wholesale. Kc
used to vanish with it, so Medjool lost FAO's date palm Kc (public 0064) and
the irrigation engine fell back to its built-in defaults. Now a stage with no
Kc of its own takes the Kc of the nearest ancestor stage with the same code.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.farms.crop_thresholds import resolve_phenology_stages
from app.modules.irrigation.engine import resolve_kc

# Crop-level date palm stages as 0038 + 0064 seed them (shape trimmed).
_CROP = {
    "stages": [
        {"code": "dormancy", "order": 1},
        {"code": "fruit_set", "order": 3, "kc": 0.90},
        {"code": "kimri", "order": 4, "kc": 0.95},
        {"code": "khalal", "order": 5, "kc": 0.95},
        {"code": "rutab", "order": 6, "kc": 0.95},
        {"code": "tamar", "order": 7},
    ]
}

# Medjool's nine-stage calendar (0097) carries no Kc.
_MEDJOOL = {
    "stages": [
        {"code": c, "order": i}
        for i, c in enumerate(
            [
                "dormancy",
                "pollination",
                "fruit_set",
                "kimri",
                "khalal",
                "rutab",
                "tamar",
                "harvest",
                "post_harvest",
            ],
            start=1,
        )
    ]
}


def _kc(doc: dict, code: str):
    return next(s.get("kc") for s in doc["stages"] if s["code"] == code)


def test_variety_stage_inherits_crop_kc_by_code() -> None:
    out = resolve_phenology_stages(crop_stages=_CROP, variety_override=_MEDJOOL)
    assert _kc(out, "fruit_set") == 0.90
    assert _kc(out, "kimri") == _kc(out, "khalal") == _kc(out, "rutab") == 0.95


def test_stages_the_crop_does_not_know_keep_no_kc() -> None:
    out = resolve_phenology_stages(crop_stages=_CROP, variety_override=_MEDJOOL)
    for code in ("dormancy", "pollination", "tamar", "harvest", "post_harvest"):
        assert _kc(out, code) is None


def test_own_kc_always_wins() -> None:
    variety = {"stages": [{"code": "kimri", "kc": 1.0}]}
    out = resolve_phenology_stages(crop_stages=_CROP, variety_override=variety)
    assert _kc(out, "kimri") == 1.0


def test_strain_inherits_from_variety_before_crop() -> None:
    variety = {"stages": [{"code": "kimri", "kc": 0.80}]}
    strain = {"stages": [{"code": "kimri"}, {"code": "khalal"}]}
    out = resolve_phenology_stages(
        crop_stages=_CROP, variety_override=variety, strain_override=strain
    )
    assert _kc(out, "kimri") == 0.80  # nearest ancestor: the variety
    assert _kc(out, "khalal") == 0.95  # variety silent, crop fills it


def test_inputs_are_not_mutated() -> None:
    before = [dict(s) for s in _MEDJOOL["stages"]]
    resolve_phenology_stages(crop_stages=_CROP, variety_override=_MEDJOOL)
    assert _MEDJOOL["stages"] == before


def test_code_keyed_dict_layout() -> None:
    variety = {"stages": {"kimri": {"order": 4}}}
    out = resolve_phenology_stages(crop_stages=_CROP, variety_override=variety)
    assert out["stages"]["kimri"]["kc"] == 0.95


def test_irrigation_engine_now_reads_the_inherited_kc() -> None:
    out = resolve_phenology_stages(crop_stages=_CROP, variety_override=_MEDJOOL)
    fruit_set = resolve_kc(growth_stage="fruit_set", phenology_stages=out)
    assert (fruit_set.value, fruit_set.source) == (Decimal("0.9"), "phenology")
    # Before D19 the same stage resolved to the built-in 1.10.
    before = resolve_kc(growth_stage="fruit_set", phenology_stages=_MEDJOOL)
    assert (before.value, before.source) == (Decimal("1.10"), "stage_default")
