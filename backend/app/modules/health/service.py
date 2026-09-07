"""Reading the per-crop health catalog, and resolving one block against it.

Two callers, both of which already load a farm's health evidence:

  * ``farms/blocks_summary_router`` — map polygons and the block dock
  * ``insights/service.get_farm_health_summary`` — the scorecard

Each reads the catalog once per request and asks it for a definition per
block. The catalog is small — one row per crop that needs its own values,
so tens of rows, not thousands — and it is platform data that changes only
when a seed file does.

Three tiers, shallow-merged, deepest winning per key:

    PLATFORM_DEFAULT_DEFINITION
      <- public.crop_health_definitions, merged along the crop path
        <- farms.health_definition                    (the farm override)

A block on ``mango.keitt`` takes ``mango``'s keys, then ``mango.keitt``'s on
top, then its farm's, and `PLATFORM_DEFAULT_DEFINITION` for anything none of
them named. That is the same rule
`app.modules.farms.crop_thresholds.resolve_thresholds` already applies to
the catalog's other inherited defaults, and following it means a reader who
knows one knows the other.

The farm override is the deepest tier and applies to EVERY block on the
farm, whatever its crop. A farm that grows two crops and overrides
`stale_after_hours` overrides it for both — the override is about the
farm's own operations, such as how often its sweep really runs, not about
agronomy, which is what the crop tier is for.

Merging the raw bodies and parsing once — rather than parsing each level
and merging the objects — is what makes a partial definition possible. A
parsed `HealthDefinition` has every field populated, so merging two of them
would let the shallow level's *defaults* overwrite the deep level's silence
and there would be no way to say "inherit this one".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.health_definition import (
    PLATFORM_DEFAULT_DEFINITION,
    HealthDefinition,
    parse_definition,
)

# Which tier had the last word. Rendered beside the class, because "why is
# my block red" has two halves and this is the other one: the reason says
# what the evidence showed, the source says whose rule read it.
DefinitionSource = Literal["platform", "crop", "farm"]


@dataclass(frozen=True, slots=True)
class ResolvedDefinition:
    """A definition and where it came from.

    ``crop_path`` and ``version`` describe the CROP row that contributed,
    not the block's own crop — a block on ``mango.keitt`` judged by a
    definition authored at ``mango`` reports ``mango``. That is what makes
    "edit the rule that produced this" a findable action.

    Both are None when no crop row applied, whatever ``source`` says: a farm
    override over the platform default is ``source="farm"`` with no crop
    behind it.
    """

    definition: HealthDefinition
    source: DefinitionSource
    crop_path: str | None = None
    version: int | None = None


class CropHealthDefinitions:
    """The catalog, indexed by crop path, with the resolution rule.

    Not frozen and not a dataclass: it memoises. A farm's blocks are mostly
    one or two crops, so a 36-block request resolves two paths and reads the
    cache 34 times instead of merging and re-parsing per block.
    """

    __slots__ = ("_by_path", "_cache", "_farm_override", "_versions")

    def __init__(
        self,
        by_path: Mapping[str, Mapping[str, Any]],
        *,
        versions: Mapping[str, int] | None = None,
        farm_override: Mapping[str, Any] | None = None,
    ) -> None:
        self._by_path = dict(by_path)
        self._versions = dict(versions or {})
        # Baked in rather than passed to `for_path`, so the memo cannot be
        # keyed on the crop path alone while the answer depends on two
        # things. One instance is one farm's view of the catalog.
        self._farm_override = dict(farm_override) if farm_override else None
        self._cache: dict[str | None, ResolvedDefinition] = {}

    def __len__(self) -> int:
        return len(self._by_path)

    def for_path(self, crop_path: str | None) -> ResolvedDefinition:
        """The definition that applies to a block on ``crop_path``, and where
        it came from.

        ``None`` — a block with no current crop assignment — skips the crop
        tier. It is not an error and not Unknown: a block without a crop
        still has alerts, and whether a tree ran on it is still the question
        health answers. Its farm's override still applies.
        """
        if crop_path in self._cache:
            return self._cache[crop_path]
        resolved = self._resolve(crop_path)
        self._cache[crop_path] = resolved
        return resolved

    def _resolve(self, crop_path: str | None) -> ResolvedDefinition:
        merged: dict[str, Any] = {}
        matched_path: str | None = None

        segments = crop_path.split(".") if crop_path else []
        # Shallowest first, so the deeper level's keys land on top.
        #
        # Split on "." and compare whole strings; never `LIKE 'mango.%'`.
        # Crop codes contain underscores (`sugar_beet`, `date_palm`) and `_`
        # is a single-character wildcard in LIKE, so a pattern match here
        # would let `sugarXbeet` inherit sugar beet's definition.
        for depth in range(1, len(segments) + 1):
            candidate = ".".join(segments[:depth])
            body = self._by_path.get(candidate)
            if body is not None:
                # Deepest wins, so the last one seen is the one to report.
                matched_path = candidate
                merged.update(body)

        # The farm has the last word: over whatever the crop tier resolved
        # to, and over the platform default when it resolved to nothing.
        has_farm = bool(self._farm_override)
        if self._farm_override:
            merged.update(self._farm_override)

        source: DefinitionSource = (
            "farm" if has_farm else ("crop" if matched_path is not None else "platform")
        )
        if source == "platform":
            return ResolvedDefinition(PLATFORM_DEFAULT_DEFINITION, "platform")
        # `parse_definition` and not `HealthDefinition(**merged)`: the body
        # comes from the database, and the loader that wrote it may be older
        # than this process. Re-checking costs one dict scan and turns a key
        # this version does not know into a loud error instead of a
        # TypeError from the constructor.
        return ResolvedDefinition(
            parse_definition(merged),
            source,
            crop_path=matched_path,
            version=self._versions.get(matched_path) if matched_path else None,
        )


async def load_health_definitions(session: AsyncSession, *, farm_id: UUID) -> CropHealthDefinitions:
    """Read the crop catalog and one farm's override. Two statements.

    Always two, whether or not the farm has an override, so a caller's query
    count does not depend on tenant data.

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
                    SELECT crop_path, definition, version
                    FROM public.crop_health_definitions
                    ORDER BY crop_path
                    """
                )
            )
        )
        .mappings()
        .all()
    )
    override = (
        await session.execute(
            text(
                """
                SELECT health_definition
                FROM farms
                WHERE id = :farm_id AND deleted_at IS NULL
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {"farm_id": farm_id},
        )
    ).first()
    # A farm id that matches nothing gives no override rather than an error.
    # Both callers have already resolved the farm; raising a second, different
    # not-found from inside a health read would turn a missing farm into a 500
    # on a page that had already decided what to say about it.
    farm_override = override.health_definition if override is not None else None

    return CropHealthDefinitions(
        {r["crop_path"]: dict(r["definition"] or {}) for r in rows},
        versions={r["crop_path"]: int(r["version"]) for r in rows},
        farm_override=farm_override,
    )
