"""Load the Medjool v2 findings and trees into an AgriPulse environment.

Reads docs/trees/medjool_v2: the 83-row findings catalogue and the 15 tree
definitions (the 14 of "Medjool Decision Trees v2" plus tree 15, cold injury).

* Findings: POST each row. A code that already exists is never changed:
  platform finding codes are shared across crops, so a PATCH would reword
  another crop's cards. An existing row that matches the file is fine; one
  that differs is reported and counts as a failure, to be resolved by hand.
* Trees: each one is created as a beta DRAFT. A tree that already exists gets
  a new draft version instead. This script never publishes: publishing is
  the owner's call (decision D8), done in the Beta designer.

Needs a platform-admin bearer token in AGRIPULSE_TOKEN and the API base in
AGRIPULSE_API, e.g. https://api.agripulse.cloud/api/v1.

    python scripts/load_medjool_v2_trees.py --dry-run
    python scripts/load_medjool_v2_trees.py
    python scripts/load_medjool_v2_trees.py date_palm_medjool_operations   # some trees only
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


def _load_findings(findings: list[dict[str, object]]) -> int:
    status, text = _call("GET", "/decision-tree-findings")
    if status != 200:
        print(f"finding list failed: {status} {text}")
        return 1
    existing = {row["code"]: row for row in json.loads(text)["findings"]}
    failed = 0
    for finding in findings:
        stored = existing.get(finding["code"])
        if stored is not None:
            differs = [k for k, v in finding.items() if stored.get(k) != v]
            if differs:
                print(f"EXISTS, differs on {differs}, not changed: {finding['code']}")
                failed += 1
            else:
                print(f"exists, identical: {finding['code']}")
            continue
        status, text = _call("POST", "/decision-tree-findings", finding)
        print(f"{status} finding create {finding['code']}")
        if status not in (200, 201):
            print(text)
            failed += 1
    return failed


def _load_trees(definitions: list[dict[str, object]]) -> int:
    status, text = _call("GET", "/platform/decision-trees/beta")
    if status != 200:
        print(f"tree list failed: {status} {text}")
        return 1
    existing = {t["code"]: t["id"] for t in json.loads(text)}
    failed = 0
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
    return failed


def load(dry_run: bool, trees_only: list[str]) -> int:
    findings = json.loads((TREES / "findings.json").read_text(encoding="utf-8"))
    definitions = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(TREES.glob("*.definition.json"))
    ]
    if trees_only:
        definitions = [d for d in definitions if d["code"] in trees_only]
    print(f"{len(findings)} findings, {len(definitions)} trees")
    if dry_run:
        for d in definitions:
            print(f"would load draft {d['code']}")
        return 0
    failed = _load_findings(findings) + _load_trees(definitions)
    return 1 if failed else 0


def main() -> int:
    if not API or not TOKEN:
        print("Set AGRIPULSE_API and AGRIPULSE_TOKEN.")
        return 2
    args = sys.argv[1:]
    return load(
        dry_run="--dry-run" in args,
        trees_only=[a for a in args if not a.startswith("--")],
    )


if __name__ == "__main__":
    sys.exit(main())
