"""Audit a tenant's authored rules + per-rule overrides (PR-F sunset).

Lists every row in ``tenant_<id>.tenant_rules`` and
``tenant_<id>.rule_overrides`` so a human can hand-translate them
into the new tree-as-alert model. Read-only — never mutates.

Usage:

    .venv/Scripts/python.exe scripts/sunset-rules/audit_tenant_rules.py \\
        --schema tenant_<hex>

The script connects via the same Settings the app uses (so DATABASE_URL
flows through whatever env-var or .env file is current). It does NOT
authenticate — run it from a host that already has DB credentials.

Output is two sections per tenant:

  1. ``rule_overrides`` rows — usually threshold tweaks. Translate to
     ``tenant.tree_parameter_overrides`` rows on the new platform
     ``ndvi_baseline_alert_v1`` tree (via the PR-C settings UI).
  2. ``tenant_rules`` rows — wholly tenant-authored predicates.
     Translate to a tenant-authored decision tree via the PR-D editor
     at ``/settings/decision-trees/new``, with ``kind: alert`` on the
     fired leaf.

Why no auto-translation:
  * Override rows that change the *predicate shape* don't map cleanly
    to parameter overrides; a human needs to decide whether to keep
    the legacy semantics or fold them into the platform tree's
    parameter knobs.
  * Tenant rules with multiple predicates need the human to draw the
    tree shape, not flatten into a single node.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any

from sqlalchemy import text

from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema

_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]+$")


async def _list_overrides(session: Any, schema: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                f"SELECT rule_code, is_disabled, severity, conditions, actions, "
                f"       updated_at FROM {schema}.rule_overrides "
                f"WHERE deleted_at IS NULL ORDER BY rule_code"
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _list_tenant_rules(session: Any, schema: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                f"SELECT code, name_en, severity, status, conditions, actions, "
                f"       applies_to_crop_categories, updated_at "
                f"FROM {schema}.tenant_rules "
                f"WHERE deleted_at IS NULL ORDER BY code"
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _table_exists(session: Any, schema: str, table: str) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": schema, "t": table},
        )
    ).first()
    return row is not None


async def _audit(schema: str) -> int:
    factory = AsyncSessionLocal()
    async with factory() as session:
        if not await _table_exists(session, schema, "rule_overrides"):
            print(
                f"[{schema}] no `rule_overrides` table — schema may not exist "
                "or the rules tables have already been dropped.",
                file=sys.stderr,
            )
            return 1
        overrides = await _list_overrides(session, schema)
        tenant_rules = (
            await _list_tenant_rules(session, schema)
            if await _table_exists(session, schema, "tenant_rules")
            else []
        )

    print(f"# Audit for {schema}")
    print()
    print(f"## rule_overrides ({len(overrides)} rows)")
    if not overrides:
        print("_none_")
    else:
        print(
            "Translate threshold-only overrides into tenant "
            "`tree_parameter_overrides` rows on the platform "
            "`ndvi_baseline_alert_v1` tree (PR-C). Structural overrides "
            "need a manual tree fork."
        )
        for row in overrides:
            print(f"\n### {row['rule_code']}")
            _emit_row(row)
    print()
    print(f"## tenant_rules ({len(tenant_rules)} rows)")
    if not tenant_rules:
        print("_none_")
    else:
        print(
            "Translate each row into a tenant-authored decision tree at "
            "`/settings/decision-trees/new`. Use `kind: alert` on the "
            "fired leaf and copy the severity / action text verbatim."
        )
        for row in tenant_rules:
            print(f"\n### {row['code']} — {row['name_en']}")
            _emit_row(row)
    return 0


def _emit_row(row: dict[str, Any]) -> None:
    for key in ("severity", "is_disabled", "status", "applies_to_crop_categories"):
        if key in row and row[key] is not None:
            print(f"- **{key}:** `{row[key]}`")
    if row.get("conditions"):
        print("- **conditions:**")
        print(
            f"  ```json\n  {json.dumps(row['conditions'], indent=2, ensure_ascii=False)}\n  ```"
        )
    if row.get("actions"):
        print("- **actions:**")
        print(
            f"  ```json\n  {json.dumps(row['actions'], indent=2, ensure_ascii=False)}\n  ```"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        required=True,
        help="Tenant schema name, e.g. `tenant_abc123...`",
    )
    args = parser.parse_args()
    schema = sanitize_tenant_schema(args.schema)
    if not _SCHEMA_RE.fullmatch(schema):
        print(f"Invalid schema name: {schema!r}", file=sys.stderr)
        return 2
    return asyncio.run(_audit(schema))


if __name__ == "__main__":
    sys.exit(main())
