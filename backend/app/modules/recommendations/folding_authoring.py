"""Storing and publishing a beta (folding) decision tree.

This is the half of the unified decision tree engine that makes a beta tree
exist. The compiler validates a definition, the engine walks one, the
designer draws one — and without this module none of them can be saved.

Deliberately a separate module from ``service.py``'s
``DecisionTreesAuthorService`` rather than more methods on it. The two
authoring flows share a shape — create, append a draft, publish, discard —
and almost nothing else:

  * the old flow takes YAML text and compiles it with ``loader.compile_tree``;
    this one takes a JSON object and compiles it with
    ``folding_compiler.compile_folding_tree``;
  * the old compiler raises on the first problem with a formatted English
    string; this one returns every problem as a structured object with an
    Arabic message beside the English, because the designer renders each one
    next to the node it names;
  * a live tree runs in the nightly sweep; a beta tree never does.

Mixing them would have meant a branch in every method on a class the live
editor depends on.

What is shared is the storage: one `public.decision_trees` row and its
`public.decision_tree_versions` rows, with `stage` saying which engine the
tree belongs to and `definition` holding the beta body (public migrations
0091 and 0092). One catalogue, one version history, one publish rule.

Design: docs/proposals/unified-decision-tree-engine.md sections 4, 5, 6.5, 9.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import get_audit_service
from app.modules.recommendations.findings import FindingDef, resolve_findings
from app.modules.recommendations.folding_compiler import (
    CompileError,
    FoldingCompileError,
    compile_folding_tree,
    hash_compiled,
)
from app.modules.recommendations.repository import RecommendationsRepository
from app.shared import clock

# The stage value a tree authored here carries. The sweep's tree query
# filters on `stage = 'live'`, so this one value is what keeps every tree in
# this module out of production until the sweep is wired to the folding
# engine.
BETA_STAGE = "beta"


# ---------------------------------------------------------------------
# Errors
#
# Named like the private authoring errors in `service.py` and mapped at the
# route layer the same way. They stay private to the module because the
# router is the only thing that catches them.
# ---------------------------------------------------------------------


class BetaTreeNotFoundError(LookupError):
    """No beta tree with this id in the caller's scope.

    Raised for "not yours" and for "that is a live tree" as well as for "no
    such row". The three are not distinguished on purpose: telling an
    unauthorised caller which ids exist is a worse trade than a slightly
    vague message.
    """

    def __init__(self, tree_id: UUID) -> None:
        super().__init__(f"No beta decision tree with id {tree_id}")
        self.tree_id = tree_id


class BetaTreeCodeExistsError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(f"A decision tree with code {code!r} already exists")
        self.code = code


class BetaVersionNotFoundError(LookupError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"No version {version_id} on this tree")
        self.version_id = version_id


class BetaNoDraftError(ValueError):
    """Discard was asked for and the newest version is published.

    A published version is history: `recommendations.tree_version` and
    `decision_tree_block_verdicts.tree_version` are bare integers with no
    foreign key, so removing one strands every row that names it.
    """

    def __init__(self, tree_id: UUID) -> None:
        super().__init__("This tree has no unpublished draft to discard")
        self.tree_id = tree_id


class BetaDryRunUnavailableError(RuntimeError):
    """The dry run could not build a context for this block."""


# ---------------------------------------------------------------------
# Compiler errors → the 422 body
# ---------------------------------------------------------------------


def compile_errors_to_body(errors: tuple[CompileError, ...] | list[CompileError]) -> dict[str, Any]:
    """The pinned 422 body:

        {"errors": [{"node_id": str|null, "rule": str,
                     "message_en": str, "message_ar": str}]}

    ``node_ids`` is carried alongside ``node_id`` rather than instead of it.
    The contract names ``node_id``, and a rule such as "these paths never
    reach stop" is about several nodes at once — the designer highlights
    every one of them, so dropping the rest would make the list misleading
    about how much is wrong.

    Every error carries Arabic. The compiler writes both languages for every
    rule it has, so there is nothing to translate here and nothing to fall
    back to. If a message ever arrives without Arabic, the English is
    repeated rather than an empty string: a blank message on an Arabic screen
    reads as "no reason given", which is worse than untranslated text.
    """
    return {
        "errors": [
            {
                "node_id": error.node_id,
                "node_ids": list(error.node_ids),
                "rule": error.rule,
                "message_en": error.message_en,
                "message_ar": error.message_ar or error.message_en,
            }
            for error in errors
        ]
    }


class FoldingTreeAuthorService:
    """Create, version, publish and dry-run beta trees.

    ``tenant_id`` is the authoring scope, exactly as it is for the live
    editor: a UUID authors that tenant's own trees, ``None`` is the platform
    scope and authors ``tenant_id IS NULL`` rows. Every read and write below
    carries it, so one tenant's beta trees are never visible to another's.
    """

    def __init__(self, *, public_session: AsyncSession, tenant_id: UUID | None) -> None:
        self._public = public_session
        self._tenant_id = tenant_id
        self._repo = RecommendationsRepository(
            tenant_session=public_session,  # unused on every authoring path
            public_session=public_session,
        )
        self._audit = get_audit_service()
        self._log = get_logger(__name__)

    # ---- The catalogue the compiler checks against --------------------

    async def known_codes(self, *, tenant_schema: str | None = None) -> set[str]:
        """The finding codes a `registers` block may name.

        The same resolution the fold does, so a code the compiler accepts is
        a code the fold can read. `resolve_findings` is the one place the
        platform-wins rule lives; this asks it for the names only.

        An absent catalogue table yields an empty set. The compiler then
        rejects every entry in `registers`, naming each code, which is the
        honest failure: the shared vocabulary is not there, so no tree can
        be published against it.
        """
        return set(await self._finding_catalogue(tenant_schema=tenant_schema))

    # ---- Reads --------------------------------------------------------

    async def list_trees(self) -> list[dict[str, Any]]:
        rows = await self._repo.list_all_trees(
            visible_to_tenant_id=self._tenant_id, stage=BETA_STAGE
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            latest = await self._repo.get_latest_version(tree_id=row["id"])
            out.append(
                {
                    **row,
                    "draft_version": (
                        latest["version"]
                        if latest is not None and latest["published_at"] is None
                        else None
                    ),
                }
            )
        return out

    async def get_tree(self, tree_id: UUID) -> dict[str, Any]:
        tree = await self._own_tree_or_raise(tree_id)
        versions = await self._repo.list_versions_for_tree(tree_id=tree_id)
        current_version: int | None = None
        for version in versions:
            if version["id"] == tree["current_version_id"]:
                current_version = version["version"]
                break

        # The body the designer opens: the draft when there is one, the
        # published version otherwise. Deciding it here rather than in the
        # canvas means the editor has one field to read and cannot open the
        # published version while a draft is sitting in front of it.
        latest = versions[0] if versions else None
        draft = latest if latest is not None and latest["published_at"] is None else None
        opening = draft
        if opening is None:
            opening = next((v for v in versions if v["id"] == tree["current_version_id"]), latest)

        return {
            **tree,
            "current_version": current_version,
            "draft_version": draft["version"] if draft is not None else None,
            "definition": opening["definition"] if opening is not None else None,
            "definition_version": opening["version"] if opening is not None else None,
            "versions": [dict(v) for v in versions],
        }

    async def _own_tree_or_raise(self, tree_id: UUID) -> dict[str, Any]:
        tree = await self._repo.get_tree_by_id(
            tree_id, scope_tenant_id=self._tenant_id, stage=BETA_STAGE
        )
        if tree is None:
            raise BetaTreeNotFoundError(tree_id)
        return tree

    # ---- Writes -------------------------------------------------------

    async def _compile(
        self, definition: dict[str, Any], *, tenant_schema: str | None
    ) -> dict[str, Any]:
        """Compile, or raise `FoldingCompileError` with every problem found.

        Always ahead of any database write. A definition that cannot compile
        must not leave a half-created tree row behind, and a draft that the
        engine cannot walk is worse than no draft: the author saves, the
        canvas reloads it, and nothing says why the publish button is dead.
        """
        codes = await self.known_codes(tenant_schema=tenant_schema)
        return compile_folding_tree(definition, known_codes=codes)

    async def create_tree(
        self,
        *,
        code: str,
        definition: dict[str, Any],
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str | None = None,
    ) -> dict[str, Any]:
        """A new beta tree and its v1 draft.

        The code must be free in both scopes, the same rule the live editor
        enforces: a tenant code that shadows a platform code makes every
        lookup by code ambiguous, and `stage` does not make it less so — the
        two catalogues share one table and one uniqueness rule.

        v1 is a draft. Publishing is a separate call, so the first version
        goes through the same review as every later one.
        """
        if (
            await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id) is not None
            or await self._repo.get_tree_by_code(code, scope_tenant_id=None) is not None
        ):
            raise BetaTreeCodeExistsError(code)

        compiled = await self._compile(definition, tenant_schema=tenant_schema)
        if compiled.get("code") != code:
            raise FoldingCompileError(
                [
                    CompileError(
                        rule="tree-code-mismatch",
                        message_en=(
                            f"The definition's code is {compiled.get('code')!r} but the "
                            f"tree is being created as {code!r}."
                        ),
                        message_ar=(
                            f"رمز التعريف هو {compiled.get('code')!r} بينما تُنشأ الشجرة "
                            f"باسم {code!r}."
                        ),
                    )
                ]
            )

        crop_path = compiled.get("crop_path")
        crop_id = await self._repo.resolve_crop_id(
            compiled.get("crop_code") or (crop_path.split(".")[0] if crop_path else None)
        )
        tree_id = await self._repo.insert_tree(
            code=code,
            tenant_id=self._tenant_id,
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=crop_id,
            crop_path=crop_path,
            crop_paths=compiled.get("crop_paths") or [],
            country_codes=compiled.get("country_codes") or [],
            soil_textures=compiled.get("soil_textures") or [],
            scope=compiled.get("scope") or "block",
            stage=BETA_STAGE,
            applicable_regions=compiled.get("applicable_regions") or [],
            actor_user_id=actor_user_id,
        )
        await self._repo.insert_version(
            tree_id=tree_id,
            version=1,
            definition=definition,
            tree_compiled=compiled,
            compiled_hash=hash_compiled(compiled),
            notes=notes,
            published_at=None,
            published_by=None,
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.beta_tree_created",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree_id,
            farm_id=None,
            details={"code": code, "version": 1, "stage": BETA_STAGE},
        )
        return await self.get_tree(tree_id)

    async def append_version(
        self,
        *,
        tree_id: UUID,
        definition: dict[str, Any],
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str | None = None,
    ) -> dict[str, Any]:
        """Append a draft, or return the tree unchanged when nothing moved.

        The no-op on an unchanged compiled hash is deliberate and matches the
        live editor: the canvas saves liberally, and a new version row per
        keystroke would bury the history that matters.

        It is also why `discard_draft` exists. Re-saving an earlier body does
        not undo a draft — it inserts a *new* version, because the hash
        differs from the draft's — but re-saving the *draft's own* body does
        nothing at all, so an author who saved something wrong and wants it
        gone has to delete it, not save over it.
        """
        tree = await self._own_tree_or_raise(tree_id)
        compiled = await self._compile(definition, tenant_schema=tenant_schema)
        compiled_hash = hash_compiled(compiled)

        latest = await self._repo.get_latest_version(tree_id=tree_id)
        if latest is not None and latest["compiled_hash"] == compiled_hash:
            return await self.get_tree(tree_id)

        next_version = (latest["version"] if latest is not None else 0) + 1
        version_id = await self._repo.insert_version(
            tree_id=tree_id,
            version=next_version,
            definition=definition,
            tree_compiled=compiled,
            compiled_hash=compiled_hash,
            notes=notes,
            published_at=None,
            published_by=None,
        )
        # The tree row's name, description and targeting are NOT touched
        # here. A draft is invisible until published — that is the point of
        # the draft state — and stamping the catalogue from it would rename
        # the tree on every reader's screen while the engine still holds the
        # published version. `publish_version` stamps them instead.
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.beta_tree_version_appended",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=version_id,
            farm_id=None,
            details={"code": tree["code"], "version": next_version},
        )
        return await self.get_tree(tree_id)

    async def publish_version(
        self,
        *,
        tree_id: UUID,
        version_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Stamp one version published and make it the tree's current one.

        Publishing a beta tree does not put it in front of anybody: the
        sweep's tree query filters on `stage = 'live'`. It fixes a version
        the designer, the dry run and a reviewer can all agree on.

        Idempotent. A second publish of the same version returns the same
        answer rather than moving `published_at`, because the button is one
        click away from being pressed twice and a moved timestamp would
        rewrite the record of when the tree actually changed.
        """
        tree = await self._own_tree_or_raise(tree_id)
        version = await self._repo.get_version(version_id)
        if version is None or version["tree_id"] != tree_id:
            raise BetaVersionNotFoundError(version_id)

        published_at: datetime
        if version["published_at"] is not None:
            published_at = version["published_at"]
        else:
            published_at = clock.now()
            stamped = await self._repo.stamp_published(
                version_id=version_id,
                published_at=published_at,
                published_by=actor_user_id,
            )
            if stamped == 0:
                # Published by someone else between the read and the write.
                # Re-read rather than report a timestamp that was never
                # written.
                fresh = await self._repo.get_version(version_id)
                published_at = (
                    fresh["published_at"] if fresh and fresh["published_at"] else published_at
                )

        await self._repo.set_current_version(
            tree_id=tree_id, version_id=version_id, actor_user_id=actor_user_id
        )
        # The catalogue row follows whichever version is current. Without
        # this, publishing an earlier version to roll back would move the
        # engine and leave the newer version's name and targeting on every
        # screen, so the catalogue would describe a version nothing runs.
        compiled = version.get("tree_compiled") or {}
        if compiled:
            crop_path = compiled.get("crop_path")
            crop_id = await self._repo.resolve_crop_id(
                compiled.get("crop_code") or (crop_path.split(".")[0] if crop_path else None)
            )
            await self._repo.update_tree_metadata(
                tree_id=tree_id,
                name_en=compiled.get("name_en") or tree["name_en"],
                name_ar=compiled.get("name_ar"),
                description_en=compiled.get("description_en"),
                description_ar=compiled.get("description_ar"),
                crop_id=crop_id,
                crop_path=crop_path,
                applicable_regions=compiled.get("applicable_regions") or [],
                actor_user_id=actor_user_id,
            )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.beta_tree_version_published",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=version_id,
            farm_id=None,
            details={"code": tree["code"], "version": version["version"]},
        )
        return {
            "tree_id": tree_id,
            "code": tree["code"],
            "version_id": version_id,
            "version": version["version"],
            "published_at": published_at,
        }

    async def discard_draft(self, *, tree_id: UUID, actor_user_id: UUID | None) -> None:
        """Delete this tree's unpublished draft, if it has one.

        This route exists because appending cannot undo. `append_version` is
        a no-op when the compiled hash is unchanged, so re-saving the draft's
        own body does nothing, and saving a *different* body adds a third
        version rather than removing the second. Without a delete, one bad
        draft sits in front of every later author for ever.

        Only the newest version is a candidate, and only when it is
        unpublished. Deleting anything published would strand
        `recommendations.tree_version` and
        `decision_tree_block_verdicts.tree_version`, which record the version
        as a bare integer with no foreign key.
        """
        tree = await self._own_tree_or_raise(tree_id)
        latest = await self._repo.get_latest_version(tree_id=tree_id)
        if latest is None or latest["published_at"] is not None:
            raise BetaNoDraftError(tree_id)
        if tree["current_version_id"] == latest["id"]:
            # Belt and braces: `current_version_id` should only ever point at
            # a published row, but it is what the engine reads, so it is
            # checked on its own rather than inferred from `published_at`.
            raise BetaNoDraftError(tree_id)

        removed = await self._repo.delete_unpublished_version(version_id=latest["id"])
        if removed == 0:
            # Published while this request was in flight. The repository's
            # own `published_at IS NULL` predicate caught it.
            raise BetaNoDraftError(tree_id)
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.beta_tree_draft_discarded",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=latest["id"],
            farm_id=None,
            details={"code": tree["code"], "version": latest["version"]},
        )

    # ---- Dry run ------------------------------------------------------

    async def dry_run(
        self,
        *,
        tree_id: UUID,
        block_id: UUID,
        definition: dict[str, Any] | None,
        version_id: UUID | None,
        tenant_session: AsyncSession,
        tenant_schema: str | None = None,
    ) -> dict[str, Any]:
        """Fold one block, cell by cell, and write nothing.

        Write-free is not a comment, it is the contract. Nothing here opens a
        recommendation, closes one, writes a verdict or a trace row. An
        author folds the canvas as often as they like and the tenant's data
        is exactly as it was.

        ``definition`` wins over ``version_id`` so the designer can fold what
        is on screen without saving first. It is compiled the same way a save
        would compile it, so a body the dry run accepts is a body that saves.

        Every cell is folded, including the ones that produce no card. A
        healthy cell is an answer, and a report that showed only the cells
        with findings would hide how much of the block the tree says nothing
        about.
        """
        from app.modules.recommendations import folding_engine

        tree = await self._own_tree_or_raise(tree_id)

        resolved_version_id: UUID | None = None
        if definition is not None:
            compiled = await self._compile(definition, tenant_schema=tenant_schema)
        else:
            row = None
            if version_id is not None:
                row = await self._repo.get_version(version_id)
                if row is None or row["tree_id"] != tree_id:
                    raise BetaVersionNotFoundError(version_id)
            elif tree["current_version_id"] is not None:
                row = await self._repo.get_version(tree["current_version_id"])
            if row is None:
                row = await self._repo.get_latest_version(tree_id=tree_id)
            if row is None:
                raise BetaDryRunUnavailableError("This tree has no version to run.")
            compiled = row["tree_compiled"]
            resolved_version_id = row["id"]

        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        base_ctx, targeting, latest_indices = await self._dry_run_context(
            compiled=compiled, repo=repo, block_id=block_id, tenant_session=tenant_session
        )

        catalogue = await self._finding_catalogue(tenant_schema=tenant_schema)
        rules = folding_engine.parse_combination_rules(compiled.get("combinations"))

        cell_aggs = await repo.get_latest_cell_aggregates(block_id=block_id)
        labels = await repo.get_grid_cell_labels(block_id=block_id)

        cells: list[dict[str, Any]] = []
        for cell_id, cell_means in cell_aggs.items():
            # Only the imagery means are per-cell. Weather, soil, crop and
            # signals inherit the block, the same fidelity rule the sweep
            # holds, so swapping `indices` on the block context is the whole
            # per-cell difference.
            cell_ctx = replace(
                base_ctx,
                indices=_cell_indices(base_ctx, latest_indices, cell_means),
            )
            row_idx, col_idx = labels.get(cell_id, (None, None))
            cells.append(
                _fold_one_cell(
                    folding_engine,
                    compiled=compiled,
                    ctx=cell_ctx,
                    catalogue=catalogue,
                    rules=rules,
                    cell_id=cell_id,
                    cell_row=row_idx,
                    cell_col=col_idx,
                )
            )

        cells.sort(
            key=lambda c: (
                c["cell_row"] is None,
                c["cell_row"] if c["cell_row"] is not None else 0,
                c["cell_col"] if c["cell_col"] is not None else 0,
            )
        )
        carded = [c for c in cells if c["identity"]]
        return {
            "tree_id": tree_id,
            "code": tree["code"],
            "block_id": block_id,
            "scope": compiled.get("scope") or "block",
            "version_id": resolved_version_id,
            "targeting": targeting,
            "cells_evaluated": len(cells),
            "cells_carded": len(carded),
            "cells_errored": sum(1 for c in cells if c["error"] is not None),
            "cells_composed": sum(1 for c in carded if c["composed"]),
            "cells": cells,
        }

    async def _finding_catalogue(self, *, tenant_schema: str | None) -> dict[str, FindingDef]:
        """The catalogue rows the fold reads, keyed by code.

        The repository returns the two tables' rows unmerged and
        `resolve_findings` decides which wins: a code held by both resolves
        to the platform row and the tenant's is never read (design section
        6.2). One place decides it, and this is not that place.
        """
        platform, tenant = await self._repo.finding_catalogue_rows(tenant_schema=tenant_schema)
        return resolve_findings(platform, tenant)

    async def _dry_run_context(
        self,
        *,
        compiled: dict[str, Any],
        repo: Any,
        block_id: UUID,
        tenant_session: AsyncSession,
    ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        """The same context the sweep would build for this block.

        Returns the context, the targeting verdict, and the block's latest
        index aggregates. The aggregates come back rather than being read
        again by the caller because the trends have been merged into them
        here: a second read would be trend-free, and every per-cell walk
        would then see nothing for `{source: indices, field: trend}` while
        the block-level walk saw a value.

        Assembled here rather than reused from `service.dry_run` because that
        method is the live engine's and returns a live-engine answer. The
        snapshot loads are the same calls in the same order; if one drifts,
        an author dry-running a beta tree sees data the sweep would not.
        """
        from app.modules.farms.attribute_snapshot import load_crop_attribute_snapshot
        from app.modules.grid.snapshot import load_snapshot as load_grid_snapshot
        from app.modules.recommendations.service import (
            _merge_index_trends,
            evaluate_targeting,
        )
        from app.modules.signals.snapshot import load_snapshot as load_signals_snapshot
        from app.modules.weather.snapshot import (
            load_index_snapshot as load_weather_index_snapshot,
        )
        from app.modules.weather.snapshot import (
            load_risk_snapshot as load_weather_risk_snapshot,
        )
        from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot
        from app.modules.weather.snapshot import load_water_balance_snapshot
        from app.shared.conditions import ConditionContext

        latest_indices = await repo.get_latest_aggregate_per_index(block_id=block_id)
        _merge_index_trends(latest_indices, await repo.get_index_trends(block_id=block_id))
        farm_id = await repo.get_block_farm_id(block_id=block_id)
        (
            block_crop_id,
            crop_id,
            growth_stage,
            crop_path,
        ) = await repo.get_block_current_crop(block_id=block_id)
        soil_texture, salinity_class = await repo.get_block_soil(block_id=block_id)
        weather = (
            await load_weather_snapshot(tenant_session, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        weather_indices = (
            await load_weather_index_snapshot(tenant_session, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        weather_risks = await load_weather_risk_snapshot(tenant_session, block_id=block_id)
        water_balance = await load_water_balance_snapshot(tenant_session, block_id=block_id)
        signals = (
            await load_signals_snapshot(tenant_session, block_id=block_id, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        grid = (
            await load_grid_snapshot(
                tenant_session, self._public, block_id=block_id, tenant_id=self._tenant_id
            )
            if farm_id is not None and self._tenant_id is not None
            else None
        )
        ctx = ConditionContext.from_block_signals(
            block_id=str(block_id),
            block_attributes={
                "growth_stage": growth_stage,
                "soil_texture": soil_texture,
                "salinity_class": salinity_class,
            },
            latest_index_aggregates=latest_indices,
            weather=weather,
            weather_indices=weather_indices,
            weather_risks=weather_risks,
            water_balance=water_balance,
            signals=signals,
            grid=grid,
            crop_attributes=await load_crop_attribute_snapshot(
                tenant_session, block_crop_id=block_crop_id
            ),
        )
        # Targeting is reported, never enforced. The block picker already
        # filters to blocks this tree targets, so an author cannot reach a
        # non-matching block from the designer — but an API caller can, and a
        # tree that folds here and is skipped by the sweep is exactly the gap
        # this endpoint exists to close.
        country_code = (
            await repo.get_farm_country_code(farm_id=farm_id) if farm_id is not None else None
        )
        targeting = evaluate_targeting(
            compiled,
            crop_path=crop_path,
            crop_id=crop_id,
            country_code=country_code,
            soil_texture=soil_texture,
        )
        return (
            ctx,
            {
                "matched": targeting.matched,
                "axis": targeting.axis,
                "required": list(targeting.required),
                "actual": targeting.actual,
            },
            latest_indices,
        )


def _cell_indices(base_ctx: Any, latest_indices: dict[str, Any], cell_means: Any) -> Any:
    """This cell's index readings, built the way the sweep builds them."""
    from app.modules.recommendations.service import _merge_cell_means
    from app.shared.conditions import ConditionContext

    return ConditionContext.from_block_signals(
        block_id=base_ctx.block_id,
        latest_index_aggregates=_merge_cell_means(latest_indices, cell_means),
    ).indices


def _fold_one_cell(
    folding_engine: Any,
    *,
    compiled: dict[str, Any],
    ctx: Any,
    catalogue: dict[str, Any],
    rules: Any,
    cell_id: UUID,
    cell_row: int | None,
    cell_col: int | None,
) -> dict[str, Any]:
    """Walk and fold one cell into the report's row shape.

    A walk that errored is never folded. The tree did not say it was
    finished, so the findings it collected on the way are not a conclusion —
    they are reported, because a trace without them is harder to read, but
    the card is null and the cell counts as errored, not as healthy.
    """
    walk = folding_engine.walk_tree(compiled, ctx)
    row: dict[str, Any] = {
        "cell_id": cell_id,
        "cell_row": cell_row,
        "cell_col": cell_col,
        "identity": [],
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "registered_by": list(f.registered_by),
            }
            for f in walk.findings
        ],
        "severity": None,
        "status": None,
        "action_type": None,
        "text_en": None,
        "text_ar": None,
        "composed": False,
        "rule_code": None,
        "stopped_at": walk.stopped_at,
        "error": walk.error,
    }
    if not walk.ok:
        return row
    try:
        card = folding_engine.fold(walk.findings, catalogue=catalogue, rules=rules)
    except folding_engine.UnknownFindingError as exc:
        # The compiler checks every code at publish, so this means the
        # catalogue and the published tree have drifted apart since. Reported
        # on the cell rather than raised, so one missing code does not hide
        # the rest of the block's answer.
        row["error"] = str(exc)
        return row
    if card is None:
        return row
    row.update(
        {
            "identity": list(card.identity),
            "severity": card.severity,
            "status": card.status,
            "action_type": card.action_type,
            "text_en": card.text_en,
            "text_ar": card.text_ar,
            "composed": card.composed,
            "rule_code": card.rule_code,
        }
    )
    return row


def get_folding_tree_author_service(
    *, public_session: AsyncSession, tenant_id: UUID | None
) -> FoldingTreeAuthorService:
    return FoldingTreeAuthorService(public_session=public_session, tenant_id=tenant_id)
