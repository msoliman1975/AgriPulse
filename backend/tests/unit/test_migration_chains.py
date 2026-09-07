"""Both migration chains must have exactly one head.

Two branches that each add a migration pick the same next number, and the
merge keeps both files: alembic then refuses to run at all with
"Revision NNNN is present more than once", and every integration test fails
at schema setup rather than anywhere near the change that caused it.

That happened twice on one branch: tenant 0089 against `farm_tree_exclusions`
after a rebase, and public 0080 against `decision_tree_sweep_cadence`. The
tenant one was caught by hand; the public one reached CI and produced 1218
errors, all of them this.

Reads the files rather than loading alembic, so it runs in the unit suite
with no database and no config.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_VERSIONS = Path(__file__).resolve().parents[1].parent / "migrations"
_REVISION = re.compile(r'^revision(?:\s*:[^=]+)?\s*=\s*"([^"]+)"', re.MULTILINE)
_DOWN = re.compile(r"^down_revision(?:\s*:[^=]+)?\s*=\s*(.+)$", re.MULTILINE)


def _chain(tree: str) -> dict[str, list[tuple[str, str]]]:
    revisions: dict[str, list[tuple[str, str]]] = {}
    for path in sorted((_VERSIONS / tree / "versions").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        revision = _REVISION.search(source)
        down = _DOWN.search(source)
        assert revision is not None, f"{path.name} declares no revision"
        assert down is not None, f"{path.name} declares no down_revision"
        revisions.setdefault(revision.group(1), []).append(
            (path.name, down.group(1).strip().strip('"'))
        )
    return revisions


@pytest.mark.parametrize("tree", ["public", "tenant"])
def test_no_revision_number_is_used_twice(tree: str) -> None:
    duplicates = {rev: files for rev, files in _chain(tree).items() if len(files) > 1}

    assert not duplicates, (
        f"{tree} migrations reuse a revision number: {duplicates}. "
        f"Two branches picked the same next number; renumber the newer one."
    )


@pytest.mark.parametrize("tree", ["public", "tenant"])
def test_the_chain_has_exactly_one_head(tree: str) -> None:
    """A head is a revision nothing points down to."""
    chain = _chain(tree)
    pointed_at = {down for entries in chain.values() for _, down in entries}
    heads = sorted(rev for rev in chain if rev not in pointed_at)

    assert len(heads) == 1, f"{tree} migrations have {len(heads)} heads: {heads}"


@pytest.mark.parametrize("tree", ["public", "tenant"])
def test_every_down_revision_names_a_migration_that_exists(tree: str) -> None:
    """A dangling pointer is the other way a rename goes wrong."""
    chain = _chain(tree)
    for revision, entries in chain.items():
        for name, down in entries:
            if down in ("None", "none"):
                continue
            assert down in chain, f"{name} (revision {revision}) points down to {down!r}"
