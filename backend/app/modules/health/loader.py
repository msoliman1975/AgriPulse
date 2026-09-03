"""Sync per-crop health definitions from YAML into the public catalog.

One file per crop path in ``seeds/*.yaml``. ``sync_from_disk`` reads them,
checks them, and upserts ``public.crop_health_definitions`` so the catalog
matches what is on disk. Idempotent: same content, no writes.

Called at startup from ``app.core.app_factory``, beside the decision-tree
sync it deliberately mirrors.

**Everything is rejected loudly.** An unknown top-level key, an unknown key
inside ``definition``, a value outside the bounded set, a ``crop_path`` the
crop catalog has never heard of — each raises and stops the file being
written. That is the whole point of the phase, and it is a direct answer to
how the decision-tree loader fails: an unknown condition operator there
compiles, publishes and then misses for ever, because the evaluator catches
the parse error and answers "did not match". A branch that quietly never
matches, and a health key that quietly means the platform default, are the
same failure. Here the load stops instead.

A file that fails takes the whole sync down with it rather than being
skipped. A partially-applied knowledge base is worse than an old one: half
the crops would move and half would not, and nothing on any screen would
say which.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.health_definition import HealthDefinitionError, parse_definition

_log = get_logger(__name__)

_SEEDS_DIR = Path(__file__).parent / "seeds"

# Top-level keys a seed file may carry. `definition` holds the bounded body
# and is checked by `parse_definition`; the rest is provenance.
_FILE_KEYS: frozenset[str] = frozenset({"crop_path", "version", "notes", "definition"})


class HealthSeedError(ValueError):
    """A seed file that cannot be loaded as written.

    Carries the path, because the message is read in a startup log line
    where nothing else says which of a dozen files was the problem.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.detail = detail


def _seed_files() -> Iterable[Path]:
    if not _SEEDS_DIR.exists():
        return ()
    return sorted(_SEEDS_DIR.glob("*.yaml"))


def _hash_body(crop_path: str, version: int, notes: str | None, body: dict[str, Any]) -> str:
    """Content hash over everything the row stores.

    `sort_keys` so a re-ordered YAML mapping is not a change. `notes` is
    included: it is the reasoning, and an edit to it should reach the
    database rather than sitting on disk looking applied.
    """
    payload = json.dumps(
        {"crop_path": crop_path, "version": version, "notes": notes, "definition": body},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_seed(raw: Any, *, source_path: str) -> dict[str, Any]:
    """Check one seed file's contents and return the row to write.

    Pure: no database, no catalog check. Split out so the shape rules can
    be tested without a session, and so `sync_from_disk` reads as the three
    steps it is — check the file, check the crop exists, write.
    """
    if not isinstance(raw, dict):
        raise HealthSeedError(source_path, "file must be a mapping")

    unknown = sorted(set(raw) - _FILE_KEYS)
    if unknown:
        raise HealthSeedError(
            source_path,
            f"unknown key(s) {unknown}; allowed keys are {sorted(_FILE_KEYS)}",
        )

    crop_path = raw.get("crop_path")
    if not isinstance(crop_path, str) or not crop_path.strip():
        raise HealthSeedError(source_path, "crop_path must be a non-empty string")
    crop_path = crop_path.strip()

    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise HealthSeedError(
            source_path, f"version must be a whole number 1 or greater, got {version!r}"
        )

    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise HealthSeedError(source_path, "notes must be a string")

    body = raw.get("definition")
    if body is None:
        raise HealthSeedError(source_path, "definition is required")
    if not isinstance(body, dict):
        raise HealthSeedError(source_path, "definition must be a mapping")
    if not body:
        # An empty body resolves to the platform default, which is what a
        # crop with no file already gets. The row would be a promise the
        # catalog does not keep.
        raise HealthSeedError(
            source_path,
            "definition is empty; a crop that takes every platform default needs no file",
        )

    # The gate. `parse_definition` rejects an unknown key, a severity that
    # is not a severity, a class that is not one of the three, a share
    # outside (0, 1], a `stale_after_hours` under 1. It is the same
    # function the resolver runs, so a body that loads here cannot fail to
    # resolve later.
    try:
        parse_definition(body)
    except HealthDefinitionError as exc:
        raise HealthSeedError(source_path, str(exc)) from exc

    return {
        "crop_path": crop_path,
        "version": version,
        "notes": notes,
        "definition": body,
        "source_path": source_path,
        "compiled_hash": _hash_body(crop_path, version, notes, body),
    }


async def _crop_path_exists(session: AsyncSession, crop_path: str) -> bool:
    """Is this a path the crop catalog actually has?

    Three tables, because the depth decides which one holds it: `crops.code`
    for `mango`, `crop_varieties.path` for `mango.keitt`,
    `crop_variety_strains.path` for `mango.keitt.short`.

    This is the check a foreign key would have done, and cannot: there is no
    single column to point at. Without it a typo'd path writes a row that
    matches no block for ever — a definition that is present, correct, and
    reaches nothing.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT 1
                FROM public.crops
                WHERE code = :p AND is_active = TRUE
                UNION ALL
                SELECT 1 FROM public.crop_varieties WHERE path = :p
                UNION ALL
                SELECT 1 FROM public.crop_variety_strains WHERE path = :p
                LIMIT 1
                """
            ),
            {"p": crop_path},
        )
    ).first()
    return row is not None


async def sync_from_disk(public_session: AsyncSession) -> dict[str, int]:
    """Read every YAML in seeds/ and upsert the catalog.

    Returns counts so the startup log can say what happened in one line.
    Rows whose path no longer has a seed file are deleted: a definition
    withdrawn on disk has to stop applying, or removing one would need a
    migration.
    """
    files = list(_seed_files())
    seen = 0
    written = 0
    seed_paths: list[str] = []

    for path in files:
        seen += 1
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        row = parse_seed(raw, source_path=path.name)

        if not await _crop_path_exists(public_session, row["crop_path"]):
            raise HealthSeedError(
                path.name,
                f"crop_path {row['crop_path']!r} is not in the crop catalog",
            )

        seed_paths.append(row["crop_path"])
        result = await public_session.execute(
            text(
                """
                INSERT INTO public.crop_health_definitions
                       (crop_path, definition, version, notes,
                        source_path, compiled_hash)
                VALUES (:crop_path, CAST(:definition AS jsonb), :version, :notes,
                        :source_path, :compiled_hash)
                ON CONFLICT (crop_path) DO UPDATE
                   SET definition    = EXCLUDED.definition,
                       version       = EXCLUDED.version,
                       notes         = EXCLUDED.notes,
                       source_path   = EXCLUDED.source_path,
                       compiled_hash = EXCLUDED.compiled_hash,
                       updated_at    = now()
                 -- Idempotence. Without this predicate every startup would
                 -- rewrite every row and bump `updated_at`, which would make
                 -- "when did this crop's definition last change" unanswerable.
                 WHERE public.crop_health_definitions.compiled_hash
                       IS DISTINCT FROM EXCLUDED.compiled_hash
                RETURNING id
                """
            ),
            {**row, "definition": json.dumps(row["definition"])},
        )
        if result.first() is not None:
            written += 1

    # `= ANY(:paths)` with an empty list is false for every row, which
    # correctly deletes everything when the last seed file is removed.
    deleted = len(
        (
            await public_session.execute(
                text(
                    """
                    DELETE FROM public.crop_health_definitions
                    WHERE NOT (crop_path = ANY(:paths))
                    RETURNING id
                    """
                ),
                {"paths": seed_paths},
            )
        )
        .scalars()
        .all()
    )

    await public_session.commit()
    _log.info(
        "crop_health_definitions_synced",
        files=seen,
        written=written,
        deleted=deleted,
    )
    return {"files": seen, "written": written, "deleted": deleted}
