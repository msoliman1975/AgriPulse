"""Load the Medjool v2 findings and trees into an AgriPulse environment.

Reads docs/trees/medjool_v2: the 83-row findings catalogue and the 15 tree
definitions (the 14 of "Medjool Decision Trees v2" plus tree 15, cold injury).

* Findings: POST each row; a code that already exists is updated with PATCH
  so a re-run converges on the file.
* Trees: each one is created as a beta DRAFT. A tree that already exists gets
  a new draft version instead. This script never publishes: publishing is
  the owner's call (decision D8), done in the Beta designer.

Needs a platform-admin bearer token in AGRIPULSE_TOKEN and the API base in
AGRIPULSE_API, e.g. https://api.agripulse.cloud/api/v1.

    python scripts/load_medjool_v2_trees.py --dry-run
    python scripts/load_medjool_v2_trees.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "docs" / "trees" / "medjool_v2"
API = os.environ.get("AGRIPULSE_API", "").rstrip("/")
TOKEN = os.environ.get("AGRIPULSE_TOKEN", "")
NOTES = (
    "Medjool Decision Trees v2 (D3, D4, D5, D10c, D11 applied). Draft, not published."
)


def _call(method: str, path: str, payload: object | None = None) -> tuple[int, str]:
    body = (
        None
        if payload is None
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    request = urllib.request.Request(  # noqa: S310 - fixed API host
        f"{API}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed API host
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def load(dry_run: bool) -> int:
    findings = json.loads((TREES / "findings.json").read_text(encoding="utf-8"))
    definitions = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(TREES.glob("*.definition.json"))
    ]
    print(f"{len(findings)} findings, {len(definitions)} trees")
    if dry_run:
        for d in definitions:
            print(f"would create draft {d['code']}")
        return 0

    failed = 0
    for finding in findings:
        status, text = _call("POST", "/decision-tree-findings", finding)
        if status == 409:
            fields = {k: v for k, v in finding.items() if k != "code"}
            status, text = _call(
                "PATCH", f"/decision-tree-findings/{finding['code']}", fields
            )
            action = "update"
        else:
            action = "create"
        print(f"{status} finding {action} {finding['code']}")
        if status not in (200, 201):
            print(text)
            failed += 1

    status, text = _call("GET", "/platform/decision-trees/beta")
    if status != 200:
        print(f"list failed: {status} {text}")
        return 1
    existing = {t["code"]: t["id"] for t in json.loads(text)}
    for definition in definitions:
        code = definition["code"]
        if code in existing:
            status, text = _call(
                "POST",
                f"/platform/decision-trees/beta/{existing[code]}/versions",
                {"definition": definition, "notes": NOTES},
            )
            action = "new draft version"
        else:
            status, text = _call(
                "POST",
                "/platform/decision-trees/beta",
                {"code": code, "definition": definition, "notes": NOTES},
            )
            action = "create draft"
        print(f"{status} tree {action} {code}")
        if status not in (200, 201):
            print(text)
            failed += 1
    return 1 if failed else 0


def main() -> int:
    if not API or not TOKEN:
        print("Set AGRIPULSE_API and AGRIPULSE_TOKEN.")
        return 2
    return load(dry_run="--dry-run" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
