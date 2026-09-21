"""Recompile every stored beta tree version so its rules carry their names.

    python -m scripts.recompile_beta_tree_versions --dry-run
    python -m scripts.recompile_beta_tree_versions

Why this exists
---------------

``folding_compiler._check_combinations`` normalised every combination rule
without copying its ``code``. So ``CombinationRule.code`` was always None,
``FoldedCard.rule_code`` was always None, and
``decision_tree_eval_traces.matched_rule`` has been null on every row the
folding engine has ever written. Nothing could name the rule that wrote a
card.

The compiler is fixed. A stored version is not: ``tree_compiled`` was written
when the version was saved and holds the old shape. This recompiles each one
from its ``definition``, which is the version; the compiled body is a derived
artifact of it.

What it rewrites
----------------

``tree_compiled`` and ``compiled_hash``, for every version of every beta tree,
published ones included. The hash has to move with the body: append is a no-op
on an unchanged hash, so a stale hash beside a new body would make the next
save behave oddly.

Nothing else changes. The definition is untouched, no version is added, no
version is published or unpublished, and a version whose recompiled body is
identical is left alone and reported as unchanged.

Safety
------

Safe to run more than once. The second run finds every body already current
and writes nothing.

A version whose definition no longer compiles is reported and skipped, not
raised on. The finding catalogue can have moved since the version was saved —
a code retired, a tenant row removed — and one unpublishable old draft must
not stop the rest of the estate being fixed.

``--dry-run`` compiles everything, compares, and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.modules.recommendations.folding_authoring import FoldingTreeAuthorService
from app.modules.recommendations.folding_compiler import (
    FoldingCompileError,
    compile_folding_tree,
    hash_compiled,
    is_folding_shape,
)
from app.shared.db.session import AsyncSessionLocal, dispose_engine

_SELECT = text(
    """
    SELECT v.id, v.tree_id, v.version, v.definition, v.compiled_hash,
           v.published_at IS NOT NULL AS published,
           t.code
    FROM public.decision_tree_versions v
    JOIN public.decision_trees t ON t.id = v.tree_id
    WHERE v.definition IS NOT NULL
    ORDER BY t.code, v.version
    """
)

_UPDATE = text(
    """
    UPDATE public.decision_tree_versions
    SET tree_compiled = CAST(:compiled AS jsonb), compiled_hash = :hash
    WHERE id = :vid
    """
).bindparams(bindparam("vid", type_=PG_UUID(as_uuid=True)))


def _as_dict(value: Any) -> dict[str, Any] | None:
    """A definition column as a mapping, or None when it is not one."""
    import json

    if isinstance(value, dict):
        return value
    if isinstance(value, str | bytes):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def recompile(*, dry_run: bool) -> int:
    import json

    factory = AsyncSessionLocal()
    async with factory() as session:
        service = FoldingTreeAuthorService(public_session=session, tenant_id=None)
        known = await service.known_codes()
        print(f"finding catalogue: {len(known)} active code(s)")

        rows = (await session.execute(_SELECT)).mappings().all()
        print(f"versions with a definition: {len(rows)}")

        changed = 0
        unchanged = 0
        skipped_shape = 0
        failed: list[tuple[str, int, str]] = []

        for row in rows:
            definition = _as_dict(row["definition"])
            if definition is None or not is_folding_shape(definition):
                # A live (non-folding) tree's version. It has no combinations
                # block and nothing here applies to it.
                skipped_shape += 1
                continue
            try:
                compiled = compile_folding_tree(definition, known_codes=known)
            except FoldingCompileError as exc:
                first = exc.errors[0].message_en if exc.errors else str(exc)
                failed.append((str(row["code"]), int(row["version"]), first))
                continue

            new_hash = hash_compiled(compiled)
            if new_hash == row["compiled_hash"]:
                unchanged += 1
                continue

            changed += 1
            mark = "would rewrite" if dry_run else "rewrote"
            flag = " (published)" if row["published"] else ""
            print(f"  {mark} {row['code']} v{row['version']}{flag}")
            if not dry_run:
                await session.execute(
                    _UPDATE,
                    {
                        "vid": UUID(str(row["id"])),
                        "compiled": json.dumps(compiled, ensure_ascii=False),
                        "hash": new_hash,
                    },
                )

        if not dry_run:
            await session.commit()

    print("")
    print(f"changed:   {changed}")
    print(f"unchanged: {unchanged}")
    print(f"not a folding tree: {skipped_shape}")
    if failed:
        print(f"\n{len(failed)} version(s) no longer compile and were left alone:", file=sys.stderr)
        for code, version, message in failed:
            print(f"  {code} v{version}: {message}", file=sys.stderr)
    if dry_run:
        print("\nDry run. Nothing was written.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile and compare, write nothing.",
    )
    args = parser.parse_args()

    async def run() -> int:
        try:
            return await recompile(dry_run=args.dry_run)
        finally:
            await dispose_engine()

    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
