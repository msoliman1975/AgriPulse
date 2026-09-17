"""The eight seeded codes, checked against the rules their column CHECKs hold.

Public migration 0090 seeds the vocabulary the merged mango tree registers
(design section 7). A seed row that violates its own table's CHECK fails
the migration, which means it fails every integration job at setup and the
error names a constraint rather than the row. Reading the literal here
costs nothing and says which code and which field.

The seed is imported from the migration module rather than re-typed. A
second copy of eight clauses would drift from the one the database gets.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

from app.modules.recommendations.schemas import FINDING_CODE_PATTERN
from app.modules.recommendations.status_codes import STATUS_CODES

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "public"
    / "versions"
    / "0090_decision_tree_findings.py"
)

# Section 7's register list, in the order the tree reaches them. Spelled
# out because this is the list the other four parts of the work were told
# to expect; a code quietly dropped from the seed would leave a published
# tree unable to resolve one of its own registers.
_EXPECTED_CODES = (
    "ndvi_low",
    "dry",
    "nutrient_low",
    "cover_open",
    "pest_high",
    "pest_med",
    "mildew_high",
    "fly_high",
)


def _migration() -> ModuleType:
    """Import the migration by path. It is not on a package path."""
    spec = importlib.util.spec_from_file_location("_dtf_0090", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed() -> tuple[tuple[str, ...], ...]:
    return _migration()._SEED


def test_the_eight_codes_from_section_seven_are_seeded() -> None:
    assert tuple(row[0] for row in _seed()) == _EXPECTED_CODES


def test_every_seeded_code_matches_the_code_check() -> None:
    for code, *_ in _seed():
        assert re.match(FINDING_CODE_PATTERN, code), code


def test_every_seeded_status_is_a_platform_status_code() -> None:
    for row in _seed():
        code, default_status = row[0], row[5]
        assert default_status in STATUS_CODES, f"{code}: {default_status}"


def test_the_three_pest_findings_are_alerts_and_the_rest_are_issues() -> None:
    """The split that decides what a block paints before any fold runs.

    A pest or disease finding with fruit on the tree is time-bound —
    treating next week is not treating — so it argues for `alert` on its
    own. The four index findings describe a condition rather than a
    deadline, so they argue for `issue` and rely on the combination rules
    to say which one is the cause. `pest_med` is the scouting window, not
    the spray window, so it sits with the index findings.
    """
    statuses = {row[0]: row[5] for row in _seed()}

    assert statuses == {
        "ndvi_low": "issue",
        "dry": "issue",
        "nutrient_low": "issue",
        "cover_open": "issue",
        "pest_high": "alert",
        "pest_med": "issue",
        "mildew_high": "alert",
        "fly_high": "alert",
    }


def test_no_seeded_clause_contains_a_comma() -> None:
    """The rule the fold depends on, on the rows that ship with the product.

    Both CHECKs enforce it; this says which clause broke it rather than
    printing a constraint name out of a failed migration.
    """
    for row in _seed():
        code, clause_en, clause_ar = row[0], row[1], row[2]
        assert "," not in clause_en, f"{code} clause_en"
        assert "," not in clause_ar, f"{code} clause_ar"
        assert "،" not in clause_ar, f"{code} clause_ar (Arabic comma)"


def test_every_clause_is_a_fragment_not_a_sentence() -> None:
    """Lower case start, no full stop.

    A clause is joined into a sentence with others, so a capital or a
    trailing full stop lands mid-sentence on the card. There is no test
    that can read for sense; these two catch the mistake that is easy to
    make in bulk.
    """
    for row in _seed():
        code, clause_en = row[0], row[1]
        assert clause_en[0].islower(), f"{code}: clause starts with a capital"
        assert not clause_en.rstrip().endswith("."), f"{code}: clause ends with a full stop"


def test_every_seeded_row_carries_both_languages() -> None:
    """No empty Arabic.

    `clause_ar` and `name_ar` are NOT NULL, so an empty string would pass
    the database and reach an Arabic card as a gap in the sentence.
    """
    for row in _seed():
        code = row[0]
        for index, field in ((2, "clause_ar"), (4, "name_ar"), (7, "description_ar")):
            assert row[index].strip(), f"{code}: {field} is empty"


def test_arabic_fields_actually_contain_arabic() -> None:
    """An English string pasted into the Arabic column passes every other test.

    It happened before on a different table and reached production, so the
    check is cheap and worth having: at least one character in the Arabic
    block.
    """
    arabic = re.compile(r"[؀-ۿ]")
    for row in _seed():
        code = row[0]
        for index, field in ((2, "clause_ar"), (4, "name_ar"), (7, "description_ar")):
            assert arabic.search(row[index]), f"{code}: {field} has no Arabic characters"


def test_codes_and_names_are_unique() -> None:
    seed = _seed()
    codes = [row[0] for row in seed]
    names = [row[3] for row in seed]

    assert len(set(codes)) == len(codes)
    assert len(set(names)) == len(names)
