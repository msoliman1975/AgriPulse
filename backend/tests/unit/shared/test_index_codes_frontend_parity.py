"""Cross-language guard: the frontend knows every index the backend computes.

Four hand-maintained TypeScript lists mirror `STANDARD_INDEX_CODES`, and a
fifth mirrors the weather catalog. Nothing errored when they drifted, which is
why `ndmi` — seeded by public migration 0027 — was still missing from the
insights picker and both report builders a year later: the index was computed,
stored and charted everywhere except the four places a user could pick it.

The failure modes differ per list, and both are silent:

  * the spectral lists just omit the index from a dropdown, so the feature
    looks unbuilt rather than broken;
  * `WEATHER_INDEX_CODES` is worse — `parseValueRef` REJECTS an unknown code,
    which demotes the whole visual tree editor to the read-only YAML fallback.

`test_condition_source_lockstep.py` guards the condition *source* vocabulary
and shares this file's shape; it does not look at index codes, which is the
gap this closes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.indices.computation import STANDARD_INDEX_CODES

# tests/unit/shared/<this file> → parents[3] is backend/, parents[4] the repo root.
_FRONTEND = Path(__file__).resolve().parents[4] / "frontend" / "src"

_API_INDICES_TS = _FRONTEND / "api" / "indices.ts"
_CONDITION_EDIT_TS = _FRONTEND / "modules" / "decisionTrees" / "lib" / "conditionEdit.ts"
_MAPNEXT_CONSTANTS_TS = _FRONTEND / "modules" / "labs" / "mapnext" / "constants.ts"
_INDEX_CLASSES_TS = _FRONTEND / "modules" / "labs" / "console" / "indexClasses.ts"

_SKIP_IF_NO_FRONTEND = pytest.mark.skipif(
    not _API_INDICES_TS.exists(),
    reason="frontend tree not checked out (backend-only container build)",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _quoted(fragment: str) -> list[str]:
    """Every double-quoted lower_snake token in a fragment of TypeScript."""
    return re.findall(r'"([a-z0-9_]+)"', fragment)


def _union_members(text: str, name: str) -> list[str]:
    """Members of an exported string-literal union type."""
    match = re.search(rf"export type {name}\s*=([^;]+);", text)
    assert match, f"union {name} not found — did the file move or get renamed?"
    return _quoted(match.group(1))


def _array_members(text: str, name: str) -> list[str]:
    """Members of an exported array constant, e.g. `export const X = [...]`."""
    match = re.search(rf"export const {name}[^=]*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, f"array {name} not found — did the file move or get renamed?"
    return _quoted(match.group(1))


def _record_keys(text: str, name: str) -> list[str]:
    """Top-level keys of an exported `Record<...>` object literal.

    Only keys at one level of nesting are returned, so a table whose values
    are themselves objects (INDEX_CLASSES) yields the index codes rather than
    the class keys inside them.
    """
    match = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)^\}};", text, re.DOTALL | re.MULTILINE)
    assert match, f"record {name} not found — did the file move or get renamed?"
    body = match.group(1)
    # Strip nested brace/bracket bodies so only the outer keys survive.
    flattened = re.sub(r"[\[{].*?[\]}]", "", body, flags=re.DOTALL)
    return re.findall(r"^\s{2}([a-z0-9_]+)\s*:", flattened, re.MULTILINE)


@_SKIP_IF_NO_FRONTEND
@pytest.mark.parametrize(
    ("label", "path", "extract"),
    [
        (
            "INDEX_CODES (api/indices.ts)",
            _API_INDICES_TS,
            lambda t: _array_members(t, "INDEX_CODES"),
        ),
        (
            "INDEX_CODES (conditionEdit.ts)",
            _CONDITION_EDIT_TS,
            lambda t: _array_members(t, "INDEX_CODES"),
        ),
        (
            "MAP_INDEX_ORDER (mapnext/constants.ts)",
            _MAPNEXT_CONSTANTS_TS,
            lambda t: _array_members(t, "MAP_INDEX_ORDER"),
        ),
        (
            "INDEX_META (mapnext/constants.ts)",
            _MAPNEXT_CONSTANTS_TS,
            lambda t: _record_keys(t, "INDEX_META"),
        ),
        (
            "INDEX_BANDS (mapnext/constants.ts)",
            _MAPNEXT_CONSTANTS_TS,
            lambda t: _record_keys(t, "INDEX_BANDS"),
        ),
        (
            "CLASS_VOCAB (console/indexClasses.ts)",
            _INDEX_CLASSES_TS,
            lambda t: _record_keys(t, "CLASS_VOCAB"),
        ),
        (
            "INDEX_CLASSES (console/indexClasses.ts)",
            _INDEX_CLASSES_TS,
            lambda t: _record_keys(t, "INDEX_CLASSES"),
        ),
    ],
)
def test_frontend_index_list_matches_backend(label, path, extract) -> None:
    frontend = set(extract(_read(path)))
    backend = set(STANDARD_INDEX_CODES)

    missing = backend - frontend
    extra = frontend - backend
    assert not missing, (
        f"{label} is missing {sorted(missing)}. The backend computes and stores "
        "these, so they exist everywhere except where a user can pick them."
    )
    assert not extra, (
        f"{label} lists {sorted(extra)}, which the backend does not compute. "
        "Selecting one yields an index with no data behind it."
    )


@_SKIP_IF_NO_FRONTEND
def test_extraction_actually_found_something() -> None:
    """Guards the guard: a regex that matches nothing passes vacuously."""
    found = _array_members(_read(_API_INDICES_TS), "INDEX_CODES")
    assert len(found) >= 7, found
    assert "ndvi" in found
    # The nested-brace stripping in _record_keys is the fiddly part: assert it
    # returns index codes and not the class keys inside each index's array.
    classes = _record_keys(_read(_INDEX_CLASSES_TS), "INDEX_CLASSES")
    assert "ndvi" in classes
    assert "bare" not in classes, classes


@_SKIP_IF_NO_FRONTEND
def test_weather_index_codes_match_the_catalog_migrations() -> None:
    """The weather list mirrors the catalog seeds, not a Python constant.

    There is no backend tuple to compare against — the weather catalog lives
    in the database — so the migrations that seed it are the source of truth.
    Read them rather than the DB so this stays a fast unit test.
    """
    migrations = Path(__file__).resolve().parents[3] / "migrations" / "public" / "versions"
    seeded: set[str] = set()
    for path in sorted(migrations.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "weather_indices_catalog" not in source:
            continue
        # Seed rows are dict literals keyed "code"; the DDL and DELETEs are not.
        seeded.update(re.findall(r'"code":\s*"([a-z0-9_]+)"', source))
    assert seeded, "no weather catalog seeds found — did the migrations move?"

    frontend = set(_array_members(_read(_CONDITION_EDIT_TS), "WEATHER_INDEX_CODES"))
    missing = seeded - frontend
    assert not missing, (
        f"WEATHER_INDEX_CODES is missing {sorted(missing)}. Unlike the spectral "
        "lists this one is load-bearing at runtime: parseValueRef rejects an "
        "unknown code and drops the whole tree editor to the YAML fallback."
    )
