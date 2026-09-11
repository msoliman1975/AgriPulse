"""The one reading of a finding's evidence, shared by every surface.

The bug these guard: an alert email said ``Warning · My new tree — 045,
Mango Republic`` and, in the body, one sentence the leaf wrote. It never
said what was measured. The Action Center was worse — for the same alerts
it showed nothing at all, because its own formatter dropped any value
that was ``None`` and the whole snapshot was ``{"indices.ndvi.mean":
None}``.
"""

from __future__ import annotations

import pytest

from app.shared.finding_evidence import (
    evidence_label,
    evidence_rows,
    evidence_text,
    evidence_value,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("indices.ndvi.mean", "NDVI mean"),
        ("indices.ndmi.baseline_deviation", "NDMI vs its own baseline"),
        ("weather.gdd.sum", "GDD total"),
        ("block.growth_stage", "Growth stage"),
        ("crop_attribute.tree_size_class.value", "Tree size class"),
        # A shape nobody wrote a label for degrades to the key itself, not
        # to blank: an unlabelled row can still be identified.
        ("something.entirely.new", "something.entirely.new"),
    ],
)
def test_label_reads_as_words(key: str, expected: str) -> None:
    assert evidence_label(key) == expected


def test_index_code_is_upper_cased_not_title_cased() -> None:
    """NDVI, not Ndvi. Agronomists read these as acronyms."""
    assert "NDVI" in evidence_label("indices.ndvi.mean")


def test_null_reads_as_no_data_and_is_never_dropped() -> None:
    """The case this whole change came from.

    The Mango Republic tree fired BECAUSE the index was missing. A
    formatter that skips null values leaves the reader a severity word
    and no stated reason at all.
    """
    snapshot = {"indices.ndvi.mean": None}
    assert evidence_rows(snapshot) == [("NDVI mean", "no data")]
    assert evidence_text(snapshot) == "NDVI mean: no data"


def test_params_are_not_presented_as_measurements() -> None:
    """A threshold is configuration, not something the platform observed."""
    snapshot = {"indices.ndvi.mean": 0.21, "params.dry_z": -1.5}
    assert [label for label, _ in evidence_rows(snapshot)] == ["NDVI mean"]
    assert len(evidence_rows(snapshot, include_params=True)) == 2


def test_floats_keep_three_decimals() -> None:
    """0.205 and 0.214 can be two different verdicts; two decimals hides that."""
    assert evidence_value(0.2145) == "0.214"
    assert evidence_value(0.2000) == "0.2"
    assert evidence_value(0.0) == "0"


def test_booleans_and_ints_read_plainly() -> None:
    assert evidence_value(True) == "yes"
    assert evidence_value(False) == "no"
    assert evidence_value(7) == "7"


def test_order_is_stable_across_blocks() -> None:
    """Two blocks with the same finding must describe it identically —
    otherwise the digest's one message cannot stand for all of them."""
    a = {"indices.ndvi.mean": 0.2, "block.growth_stage": "flowering"}
    b = {"block.growth_stage": "flowering", "indices.ndvi.mean": 0.2}
    assert evidence_rows(a) == evidence_rows(b)


def test_arabic_labels_and_values() -> None:
    rows = evidence_rows({"indices.ndvi.mean": None}, locale="ar")
    assert rows == [("متوسط NDVI", "لا توجد بيانات")]


def test_empty_snapshot_yields_nothing_not_an_empty_heading() -> None:
    assert evidence_rows(None) == []
    assert evidence_rows({}) == []
    assert evidence_text({}) == ""


def test_identifiers_are_not_presented_as_measurements() -> None:
    """A reader asked "what did you see?" is not answered by a UUID.

    A real recommendation email went out carrying
    `cell_id: 01a0443c-e0fc-72b8-acba-879ed58093c7` under the heading
    "WHAT WE MEASURED".
    """
    snapshot = {
        "cell_id": "01a0443c-e0fc-72b8-acba-879ed58093c7",
        "indices.ndvi.mean": 0.2074,
    }
    assert evidence_rows(snapshot) == [("NDVI mean", "0.207")]


def test_how_a_value_was_obtained_is_not_the_value() -> None:
    """`source` and `index_code` say where the number came from. The label
    beside the number already names the index."""
    snapshot = {"source": "block_aggregate", "index_code": "ndvi", "indices.ndvi.mean": 0.2}
    assert [label for label, _ in evidence_rows(snapshot)] == ["NDVI mean"]


def test_any_id_suffix_is_dropped_even_if_nobody_listed_it() -> None:
    """The engine may resolve new identifiers; none of them is ever an
    observation, so the rule is the suffix rather than a fixed list."""
    snapshot = {"some_new_id": "abc", "indices.ndvi.mean": 0.2}
    assert [label for label, _ in evidence_rows(snapshot)] == ["NDVI mean"]


def test_a_snapshot_of_only_identifiers_yields_nothing() -> None:
    """And therefore no "WHAT WE MEASURED" heading at all, rather than a
    heading above a UUID."""
    assert evidence_rows({"cell_id": "x", "block_id": "y"}) == []
