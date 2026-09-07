"""The verdict table's shape must agree with the code that writes to it.

Tenant migration 0091 spells the four leaf kinds and the five status codes
into CHECK constraints. `status_codes.py` spells the same two lists in
Python. Nothing forces them to agree, and a code added on one side only
would be rejected at write time by a constraint nobody thought about — the
sweep would fail on a status the author was told was valid.

These tests read the migration file as text, so they need no database.
The integration test for the live table is separate.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.recommendations.models import DecisionTreeBlockVerdict
from app.modules.recommendations.status_codes import LEAF_KINDS, STATUS_CODES

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "tenant"
    / "versions"
    / "0091_decision_tree_block_verdicts.py"
)


def _text() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _quoted(line_prefix: str) -> set[str]:
    """The single-quoted values assigned to a module constant in the migration."""
    source = _text()
    match = re.search(rf"^{line_prefix} = \"(.+)\"$", source, re.MULTILINE)
    assert match is not None, f"{line_prefix} not found in {_MIGRATION.name}"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_the_check_lists_the_same_four_kinds_as_the_code() -> None:
    assert _quoted("_KINDS") == set(LEAF_KINDS)


def test_the_check_lists_the_same_five_statuses_as_the_code() -> None:
    assert _quoted("_STATUS_CODES") == set(STATUS_CODES)


def test_the_model_and_the_migration_hold_the_same_columns() -> None:
    """Two of five TimestampedMixin columns missing once killed 18 tests.

    The model deliberately does not use that mixin — a verdict has no author
    and is ended by valid_to, not soft-deleted — so this test is what keeps
    the two column lists in step instead.
    """
    in_migration = re.findall(r'sa\.Column\(\s*"([a-z_]+)"', _text())
    in_model = list(DecisionTreeBlockVerdict.__table__.columns.keys())

    assert sorted(in_migration) == sorted(in_model)
    assert "deleted_at" not in in_model
    assert "created_by" not in in_model


def test_the_open_row_index_coalesces_the_nullable_cell() -> None:
    """Without COALESCE the unique index would not constrain block verdicts.

    Postgres treats two NULL cell_ids as distinct, so every sweep would
    insert another open row for the same block and tree, and "the current
    verdict" would become whichever row a query happened to return first.
    """
    source = _text()

    assert "CREATE UNIQUE INDEX uq_dt_verdicts_open" in source
    assert "COALESCE(cell_id," in source
    assert "WHERE valid_to IS NULL" in source


def test_every_check_is_named_by_its_suffix_only() -> None:
    """A full name gets doubled.

    Production carries the scars: every CHECK on `blocks` is live as
    `ck_blocks_ck_blocks_*`.
    """
    for name in re.findall(r'sa\.CheckConstraint\([^)]*name="([a-z_]+)"', _text()):
        assert not name.startswith("ck_"), name


def test_the_revision_follows_0090() -> None:
    """0089 was taken twice: the branch and main each numbered one 0089."""
    source = _text()

    assert 'revision: str = "0091"' in source
    assert 'down_revision: str | Sequence[str] | None = "0090"' in source
