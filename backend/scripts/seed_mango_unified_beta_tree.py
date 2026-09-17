"""Seed `mango_unified` as a beta decision tree, from its design document.

    python -m scripts.seed_mango_unified_beta_tree
    python -m scripts.seed_mango_unified_beta_tree --publish
    python -m scripts.seed_mango_unified_beta_tree --check-only

The tree's content lives in `docs/proposals/mango-unified-tree.md` and this
script reads it from there. It is not copied into Python, because two copies
of 74 nodes drift and nothing reports it.

The write goes through `FoldingTreeAuthorService`, not through SQL. That is
the point of the script: the definition passes exactly the checks a designer
save passes, so "the seed worked" means "an author could have typed this".
Raw SQL would seed a tree the compiler might reject.

Idempotent. A second run finds the tree, appends the same definition, and
`append_version` returns without inserting because the compiled hash is
unchanged.

Two things the document and the code disagree about
---------------------------------------------------

**1. An unquoted `on:` key is the boolean True in YAML.** The document
writes each switch as

    switch:
      on: {source: weather_risk, ...}

and PyYAML (YAML 1.1) reads a bare `on` as a boolean, so the key arrives as
`True` and the compiler reports "a switch with nothing to switch on" for all
three switches. `_normalise_switch_keys` below puts the string key back. The
document is right about what it means; YAML is what cannot carry it. This is
also the clearest argument for storing the definition as JSONB: a JSON object
has one kind of key and cannot do this.

**2. The status vocabulary is not agreed.** The document's combination rules
use `issue` and `alert`, from
`app.modules.recommendations.status_codes.STATUS_CODES` — the leaf verdict
list. The folding compiler accepts `normal`, `watch`, `stressed`, `unknown`
(`folding_compiler.FOLDING_STATUSES`), which is what the design document's
section 5.5 and the pinned beta contract both name. Two of the five sessions
went one way and two the other.

`_STATUS_TRANSLATION` below maps one onto the other so this tree can be
seeded at all. It is a translation table in a seed script, not a decision:
somebody has to pick one vocabulary, and until they do, every rule this tree
publishes carries a status the document did not write. It is listed in the
pull request body for that reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from app.modules.recommendations.folding_authoring import (
    BetaTreeCodeExistsError,
    FoldingTreeAuthorService,
)
from app.modules.recommendations.folding_compiler import (
    FoldingCompileError,
    check_folding_tree,
)
from app.shared.db.session import AsyncSessionLocal, dispose_engine

TREE_CODE = "mango_unified"

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "proposals" / "mango-unified-tree.md"

# Which `## n.` section of the document each kind of YAML block lives in.
# Selecting by section rather than by the shape of the block keeps the
# illustrative snippets in section 1 out of the tree — they are fragments of
# nodes and would parse as real ones.
_PARAMETERS_SECTION = "4"
_TREE_SECTION = "5"
_COMBINATIONS_SECTION = "6"

# The document's leaf-status vocabulary → the folding compiler's. See the
# module docstring: this is a stopgap, not a decision.
_STATUS_TRANSLATION: dict[str, str] = {
    "na": "unknown",
    "very_good": "normal",
    "good": "normal",
    "issue": "watch",
    "alert": "stressed",
}


def _yaml_blocks(markdown: str) -> list[tuple[str, str]]:
    """Every fenced ```yaml block, paired with the `## n.` section it is in."""
    blocks: list[tuple[str, str]] = []
    section = ""
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        heading = re.match(r"^## (\d+)\.", lines[index])
        if heading:
            section = heading.group(1)
        if lines[index].strip() == "```yaml":
            body: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != "```":
                body.append(lines[index])
                index += 1
            blocks.append((section, "\n".join(body)))
        index += 1
    return blocks


def _normalise_switch_keys(node: Any) -> Any:
    """Put the string key `on` back where YAML turned it into `True`.

    Recursive, because a switch is nested inside a node and a node inside
    `nodes`. Only a `True` key is touched, and only when there is no `on`
    key already, so a definition that was never round-tripped through YAML
    passes through unchanged.
    """
    if isinstance(node, list):
        return [_normalise_switch_keys(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[Any, Any] = {}
    for key, value in node.items():
        stored = "on" if key is True and "on" not in node else key
        out[stored] = _normalise_switch_keys(value)
    return out


def _translate_statuses(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Rewrite each combination rule's `status` into the compiler's list.

    Returns the spec and one line per rule translated, so the run says out
    loud what it changed rather than doing it silently.
    """
    notes: list[str] = []
    for index, rule in enumerate(spec.get("combinations") or []):
        if not isinstance(rule, dict):
            continue
        status = rule.get("status")
        if isinstance(status, str) and status in _STATUS_TRANSLATION:
            rule["status"] = _STATUS_TRANSLATION[status]
            notes.append(
                f"  rule {index} ({'+'.join(rule.get('codes') or [])}): {status} -> {rule['status']}"
            )
    return spec, notes


def build_definition(doc_path: Path = DOC_PATH) -> tuple[dict[str, Any], list[str]]:
    """Assemble the whole `mango_unified` definition out of the document.

    Section 5's first block carries the tree's header — code, name, scope,
    targeting, `registers` and `root` — and its remaining blocks carry the
    nodes, two spaces indented, one block per group of checks. Section 4
    carries `parameters` and section 6 carries `combinations`.
    """
    blocks = _yaml_blocks(doc_path.read_text(encoding="utf-8"))
    parameters = [body for section, body in blocks if section == _PARAMETERS_SECTION]
    tree = [body for section, body in blocks if section == _TREE_SECTION]
    combinations = [body for section, body in blocks if section == _COMBINATIONS_SECTION]
    if not tree:
        raise SystemExit(f"No tree definition found in {doc_path}")

    spec: dict[str, Any] = yaml.safe_load(tree[0]) or {}
    nodes: dict[str, Any] = {}
    for body in tree[1:]:
        for node_id, node in (yaml.safe_load(body) or {}).items():
            if node_id in nodes:
                raise SystemExit(f"Node {node_id!r} is defined twice in {doc_path}")
            nodes[node_id] = node
    spec["nodes"] = nodes
    for body in parameters:
        spec.update(yaml.safe_load(body) or {})
    for body in combinations:
        spec.update(yaml.safe_load(body) or {})

    spec = _normalise_switch_keys(spec)
    spec, notes = _translate_statuses(spec)
    return spec, notes


async def seed(*, publish: bool, check_only: bool) -> int:
    definition, status_notes = build_definition()
    nodes = definition.get("nodes") or {}
    print(f"Read {DOC_PATH.name}")
    print(f"  nodes:        {len(nodes)}")
    print(f"  registers:    {len(definition.get('registers') or [])}")
    print(f"  parameters:   {len(definition.get('parameters') or {})}")
    print(f"  combinations: {len(definition.get('combinations') or [])}")
    if status_notes:
        print("  combination statuses translated into the compiler's vocabulary:")
        for line in status_notes:
            print(line)

    factory = AsyncSessionLocal()
    async with factory() as session:
        service = FoldingTreeAuthorService(public_session=session, tenant_id=None)
        codes = await service.known_codes()
        print(f"  finding catalogue: {len(codes)} active code(s)")
        if not codes:
            print(
                "  the finding catalogue table is absent or empty, so every "
                "`registers` entry will be rejected below"
            )

        errors = check_folding_tree(definition, known_codes=codes)
        if errors:
            print(f"\n{len(errors)} publish check(s) failed:", file=sys.stderr)
            for error in errors:
                where = error.node_id or "(whole tree)"
                print(f"  {error.rule}  {where}\n    {error.message_en}", file=sys.stderr)
            return 1
        print("  publish checks: passed")

        if check_only:
            return 0

        try:
            tree = await service.create_tree(
                code=TREE_CODE,
                definition=definition,
                notes="Seeded from docs/proposals/mango-unified-tree.md",
                actor_user_id=None,
            )
            print(f"\nCreated {TREE_CODE} ({tree['id']}) at version 1")
        except BetaTreeCodeExistsError:
            existing = next((t for t in await service.list_trees() if t["code"] == TREE_CODE), None)
            if existing is None:
                print(
                    f"{TREE_CODE!r} exists as a live tree, not a beta one. Rename or "
                    "archive it before seeding.",
                    file=sys.stderr,
                )
                return 1
            tree = await service.append_version(
                tree_id=existing["id"],
                definition=definition,
                notes="Re-seeded from docs/proposals/mango-unified-tree.md",
                actor_user_id=None,
            )
            print(
                f"\n{TREE_CODE} ({tree['id']}) already existed; newest version is "
                f"{tree['versions'][0]['version']}"
            )

        if publish:
            newest = tree["versions"][0]
            published = await service.publish_version(
                tree_id=tree["id"], version_id=newest["id"], actor_user_id=None
            )
            print(f"Published version {published['version']} at {published['published_at']}")
            print("It will not run: the sweep's tree query filters on stage = 'live'.")
        await session.commit()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the seeded version. It still never runs in the sweep.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Assemble and compile the definition, write nothing.",
    )
    parser.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="Write the assembled definition to this path as JSON and exit.",
    )
    args = parser.parse_args()

    if args.dump is not None:
        definition, _ = build_definition()
        args.dump.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {args.dump}")
        return

    async def run() -> int:
        try:
            return await seed(publish=args.publish, check_only=args.check_only)
        except FoldingCompileError as exc:
            print(f"{len(exc.errors)} publish check(s) failed:", file=sys.stderr)
            for error in exc.errors:
                print(f"  {error.rule}  {error.node_id or '(whole tree)'}", file=sys.stderr)
                print(f"    {error.message_en}", file=sys.stderr)
            return 1
        finally:
            await dispose_engine()

    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
