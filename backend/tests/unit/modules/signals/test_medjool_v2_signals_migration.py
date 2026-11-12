"""Public migration 0103: the Medjool v2 signals match the approved draft (D14).

The trees name 28 signals without a prefix. D5 adds ``date_``; D6 turns the
three typed "days since" numbers into "done" events read through
``days_since_latest``; D7 gives the trap catch its own ``_value`` signal.
``date_ripening_stage`` already exists (public 0098). This table is the rename
the tree definitions get in the next step, so it is pinned here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "public"
    / "versions"
    / "0103_medjool_v2_signals.py"
)

# Tree code -> catalog code.
TREE_TO_CATALOG = {
    "charcoal_lesions_seen": "date_charcoal_lesions_seen",
    "rachis_one_side_whitening": "date_rachis_one_side_whitening",
    "leaf_base_rot_seen": "date_leaf_base_rot_seen",
    "yellow_streaking_stunting": "date_yellow_streaking_stunting",
    "brittle_leaflets_seen": "date_brittle_leaflets_seen",
    "mite_webbing_seen": "date_mite_webbing_seen",
    "days_since_bunch_scouting": "date_bunches_scouted",
    "spathe_rot_seen": "date_spathe_rot_seen",
    "graphiola_spots_seen": "date_graphiola_spots_seen",
    "bunches_bagged": "date_bunches_bagged",
    "date_ripening_stage": "date_ripening_stage",
    "bt_applied": "date_bt_applied",
    "hollow_fruit_seen": "date_hollow_fruit_seen",
    "dates_in_storage": "date_dates_in_storage",
    "rpw_symptom_seen": "date_rpw_symptom_seen",
    "drone_crown_temp_anomaly": "date_drone_crown_temp_anomaly",
    "drone_ndre_no_seasonal_rise": "date_drone_ndre_no_seasonal_rise",
    "offshoot_or_frond_cut": "date_offshoot_or_frond_cut",
    "wounds_treated": "date_wounds_treated",
    "irrigation_method": "date_irrigation_method",
    "aerial_roots_exposed": "date_aerial_roots_exposed",
    "rodent_damage_seen": "date_rodent_damage_seen",
    "infested_waste_left": "date_infested_waste_left",
    "days_since_rpw_inspection": "date_rpw_inspection_done",
    "rpw_trap_catch": "date_rpw_trap_catch_value",
    "days_since_trap_service": "date_trap_serviced",
    "honeydew_seen": "date_honeydew_seen",
    "scale_per_leaflet": "date_scale_per_leaflet",
}

# D14 windows (None = no expiry).
WINDOWS = {
    "date_offshoot_or_frond_cut": 7,
    "date_wounds_treated": 7,
    "date_mite_webbing_seen": 7,
    "date_hollow_fruit_seen": 7,
    "date_spathe_rot_seen": 7,
    "date_rpw_trap_catch_value": 15,
    "date_bt_applied": 70,
    "date_rpw_inspection_done": None,
    "date_trap_serviced": None,
    "date_bunches_scouted": None,
    "date_bunches_bagged": None,
    "date_dates_in_storage": None,
    "date_irrigation_method": None,
}

EVENTS = {"date_rpw_inspection_done", "date_trap_serviced", "date_bunches_scouted"}
NUMERIC = {"date_rpw_trap_catch_value", "date_scale_per_leaflet"}


@pytest.fixture(scope="module")
def mig() -> Any:
    spec = importlib.util.spec_from_file_location("mig_0103", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _defs(mig: Any) -> dict[str, tuple]:
    return {d[0]: d for d in mig.DEFINITIONS}


def test_every_tree_signal_exists_once(mig: Any) -> None:
    new = _defs(mig)
    assert len(new) == len(mig.DEFINITIONS) == 27
    expected = set(TREE_TO_CATALOG.values()) - {"date_ripening_stage"}
    assert set(new) == expected
    assert "date_ripening_stage" in mig.EXISTING_DEFINITIONS


def test_kinds_and_windows_follow_the_approved_draft(mig: Any) -> None:
    for code, row in _defs(mig).items():
        kind, window = row[3], row[10]
        if code in EVENTS:
            assert kind == "event", code
        elif code in NUMERIC:
            assert kind == "numeric", code
            assert row[8] == 0, code
        elif code == "date_irrigation_method":
            assert kind == "categorical"
            assert row[4] == ["flood", "basin", "drip"]
            assert len(row[5]) == 3
        else:
            assert kind == "boolean", code
        assert window == WINDOWS.get(code, 30), code


def test_every_row_has_both_languages(mig: Any) -> None:
    for code, row in _defs(mig).items():
        name_en, name_ar, desc_en, desc_ar = row[1], row[2], row[11], row[12]
        assert name_en.strip(), code
        assert name_ar.strip(), code
        assert desc_en.startswith("Medjool trees ask: "), code
        assert desc_ar.startswith("تسأل أشجار المجدول: "), code


def test_forms_hold_every_signal_once_and_only_known_codes(mig: Any) -> None:
    members = [m for t in mig.TEMPLATES for m in t[3]]
    assert len(mig.TEMPLATES) == 5
    assert len(members) == len(set(members)) == 28
    assert set(members) == set(TREE_TO_CATALOG.values())
    for code, name_en, name_ar, _ in mig.TEMPLATES:
        assert code.startswith("medjool_")
        assert name_en
        assert name_ar


def test_everything_is_scoped_to_medjool(mig: Any) -> None:
    assert mig.SCOPE == ["date_palm.medjool"]
    assert len(mig.EXISTING_DEFINITIONS) == 15
    assert set(mig.EXISTING_TEMPLATES) == {"medjool_bearing", "medjool_new_planting"}


def test_chain_follows_0102(mig: Any) -> None:
    assert mig.revision == "0103"
    assert mig.down_revision == "0102"
