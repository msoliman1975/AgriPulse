"""The 33 platform trees as they were authored, for the tests that assert them.

These trees used to be YAML files under ``app/modules/recommendations/seeds``,
and a dozen test modules read them straight off disk to check the agronomy:
that T_NDVI branches on the recorded tree size, that the date-palm rain rule
names a forecast window, that every leaf carries an outcome, and so on.

The files are gone. Public migration 0085 carried the definitions into the
database and the app is now the only way to change one, so a file on disk
could only ever disagree with what is running. What the migration left behind
is ``data/0085_platform_decision_trees.json``, which holds each tree's YAML
text and its compiled body exactly as they shipped. This module reads that.

**Know what these tests now guard.** They guard what the platform shipped on
2026-09-10 and what migration 0085 installs into a fresh database. They do not
guard the live trees any more, and they cannot: a platform admin edits those
in the app, so their content is data, not code. Nothing here will notice a
threshold changed in production. That is a consequence of moving the trees
into the database, not an oversight — the decision is written up in
``docs/proposals/decision-trees-live-in-the-database`` and the backup for the
live content is the nightly Postgres backup.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "public"
    / "versions"
    / "data"
    / "0085_platform_decision_trees.json"
)


@lru_cache(maxsize=1)
def _by_code() -> dict[str, dict]:
    trees = json.loads(_DATA.read_text(encoding="utf-8"))
    return {t["code"]: t for t in trees}


def shipped_codes() -> list[str]:
    """Every platform tree code, sorted — the old ``sorted(seeds.glob(...))``."""
    return sorted(_by_code())


def shipped_yaml(code_or_filename: str) -> str:
    """One tree's YAML source.

    Accepts either the tree code or the old ``<code>.yaml`` filename, because
    the call sites used both and every seed file was named for its code.
    """
    code = (
        code_or_filename[: -len(".yaml")]
        if code_or_filename.endswith(".yaml")
        else (code_or_filename)
    )
    try:
        return _by_code()[code]["tree_yaml"]
    except KeyError:  # pragma: no cover - a typo in a test, not a code path
        raise AssertionError(
            f"No shipped platform tree {code!r}. Known codes: {', '.join(shipped_codes())}"
        ) from None


def shipped_compiled(code: str) -> dict:
    """One tree's compiled body, as migration 0085 installs it."""
    return _by_code()[code]["tree_compiled"]


def iter_shipped_yaml() -> list[tuple[str, str]]:
    """``(filename, yaml)`` for every tree, sorted by code.

    The filename is synthesised as ``<code>.yaml`` so the modules that used it
    as a ``source_path`` in error messages keep reading the same way.
    """
    return [(f"{code}.yaml", shipped_yaml(code)) for code in shipped_codes()]
