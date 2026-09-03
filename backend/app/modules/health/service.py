"""Reading the per-crop health catalog, and resolving one block against it.

Two callers, both of which already load a farm's health evidence:

  * ``farms/blocks_summary_router`` — map polygons and the block dock
  * ``insights/service.get_farm_health_summary`` — the scorecard

Each reads the catalog once per request and asks it for a definition per
block. The catalog is small — one row per crop that needs its own values,
so tens of rows, not thousands — and it is platform data that changes only
when a seed file does.

Resolution: shallow merge along the crop path, deepest level winning per
key, then `parse_definition` over the merged body. A block on
``mango.keitt`` takes ``mango``'s keys, then ``mango.keitt``'s on top, then
`PLATFORM_DEFAULT_DEFINITION` for anything neither named. That is the same
rule `app.modules.farms.crop_thresholds.resolve_thresholds` already applies
to the catalog's other inherited defaults, and following it means a reader
who knows one knows the other.

Merging the raw bodies and parsing once — rather than parsing each level
and merging the objects — is what makes a partial definition possible. A
parsed `HealthDefinition` has every field populated, so merging two of them
would let the shallow level's *defaults* overwrite the deep level's silence
and there would be no way to say "inherit this one".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.health_definition import (
    PLATFORM_DEFAULT_DEFINITION,
    HealthDefinition,
    parse_definition,
)


class CropHealthDefinitions:
    """The catalog, indexed by crop path, with the resolution rule.

    Not frozen and not a dataclass: it memoises. A farm's blocks are mostly
    one or two crops, so a 36-block request resolves two paths and reads the
    cache 34 times instead of merging and re-parsing per block.
    """

    __slots__ = ("_by_path", "_cache")

    def __init__(self, by_path: Mapping[str, Mapping[str, Any]]) -> None:
        self._by_path = dict(by_path)
        self._cache: dict[str | None, HealthDefinition] = {}

    def __len__(self) -> int:
        return len(self._by_path)

    def for_path(self, crop_path: str | None) -> HealthDefinition:
        """The definition that applies to a block on ``crop_path``.

        ``None`` — a block with no current crop assignment — gets the
        platform default. It is not an error and not Unknown: a block
        without a crop still has alerts, and whether a tree ran on it is
        still the question health answers.
        """
        if crop_path in self._cache:
            return self._cache[crop_path]
        definition = self._resolve(crop_path)
        self._cache[crop_path] = definition
        return definition

    def _resolve(self, crop_path: str | None) -> HealthDefinition:
        if not crop_path or not self._by_path:
            return PLATFORM_DEFAULT_DEFINITION

        merged: dict[str, Any] = {}
        found = False
        segments = crop_path.split(".")
        # Shallowest first, so the deeper level's keys land on top.
        #
        # Split on "." and compare whole strings; never `LIKE 'mango.%'`.
        # Crop codes contain underscores (`sugar_beet`, `date_palm`) and `_`
        # is a single-character wildcard in LIKE, so a pattern match here
        # would let `sugarXbeet` inherit sugar beet's definition.
        for depth in range(1, len(segments) + 1):
            body = self._by_path.get(".".join(segments[:depth]))
            if body is not None:
                found = True
                merged.update(body)

        if not found:
            return PLATFORM_DEFAULT_DEFINITION
        # `parse_definition` and not `HealthDefinition(**merged)`: the body
        # comes from the database, and the loader that wrote it may be older
        # than this process. Re-checking costs one dict scan and turns a key
        # this version does not know into a loud error instead of a
        # TypeError from the constructor.
        return parse_definition(merged)


async def load_crop_health_definitions(session: AsyncSession) -> CropHealthDefinitions:
    """Read the whole catalog. One statement, no arguments.

    The table is schema-qualified rather than relying on `search_path`. A
    tenant session carries `tenant_x, public`, so an unqualified name would
    usually work and would fail exactly when the search path has been lost —
    which this repo has seen happen mid-request, and which surfaces as an
    error naming a column rather than the missing schema.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT crop_path, definition
                    FROM public.crop_health_definitions
                    ORDER BY crop_path
                    """
                )
            )
        )
        .mappings()
        .all()
    )
    return CropHealthDefinitions({r["crop_path"]: dict(r["definition"] or {}) for r in rows})
