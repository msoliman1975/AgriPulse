"""Post-deploy steps for the organic Medjool work. Run once, after the
migrations in the same pull request are deployed.

1. ``archive-old``: archive (soft-delete) the 41 platform trees on the old
   engine (stage ``live``) listed in docs/trees/medjool/old_trees_to_archive.json,
   read from production on 2026-10-03. Uses the app's archive route, so each one is
   audited and can be restored with ``POST /decision-trees/{code}:restore``.
   Tenant-owned trees are not touched.
2. ``create``: post the 6 Medjool finding codes, then the 3 Medjool trees as
   beta drafts. Nothing is published.
3. ``update``: replace the 6 finding codes (PATCH, full replace) and post the
   current definitions as a new draft version of each Medjool tree. Used
   after the Arabic edition of the manual replaced the first Arabic text.

Both steps need a platform-admin bearer token in ``AGRIPULSE_TOKEN`` and the
API base in ``AGRIPULSE_API`` (for example https://api.agripulse.cloud/api/v1).
Bodies are sent as UTF-8 bytes read straight from the JSON files, so Arabic
text is not re-encoded on the way.

    python scripts/create_medjool_trees.py archive-old --dry-run
    python scripts/create_medjool_trees.py archive-old
    python scripts/create_medjool_trees.py create
    python scripts/create_medjool_trees.py update
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "docs" / "trees" / "medjool"
API = os.environ.get("AGRIPULSE_API", "").rstrip("/")
TOKEN = os.environ.get("AGRIPULSE_TOKEN", "")


def _call(method: str, path: str, body: bytes | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
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


def archive_old(dry_run: bool) -> int:
    snapshot = json.loads(
        (TREES / "old_trees_to_archive.json").read_text(encoding="utf-8")
    )
    codes = snapshot["codes"]
    print(f"{len(codes)} platform trees on the old engine ({snapshot['read_from']})")
    failed = 0
    for code in codes:
        if dry_run:
            print(f"would archive {code}")
            continue
        status, text = _call("DELETE", f"/decision-trees/{code}")
        print(f"{status} archive {code}")
        failed += status not in (204, 404)
    return 1 if failed else 0


def create() -> int:
    failed = 0
    for finding in json.loads((TREES / "findings.json").read_text(encoding="utf-8")):
        body = json.dumps(finding, ensure_ascii=False).encode("utf-8")
        status, text = _call("POST", "/decision-tree-findings", body)
        print(f"{status} finding {finding['code']}")
        failed += status not in (200, 201, 409)
    for path in sorted(TREES.glob("*.definition.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        body = json.dumps(
            {
                "code": definition["code"],
                "definition": definition,
                "notes": "Organic Medjool Manual, Edition 1.3. Draft, not published.",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, text = _call("POST", "/platform/decision-trees/beta", body)
        print(f"{status} tree {definition['code']}")
        if status not in (200, 201):
            print(text)
            failed += 1
    return 1 if failed else 0


def update() -> int:
    failed = 0
    for finding in json.loads((TREES / "findings.json").read_text(encoding="utf-8")):
        fields = {k: v for k, v in finding.items() if k != "code"}
        body = json.dumps(fields, ensure_ascii=False).encode("utf-8")
        status, text = _call(
            "PATCH", f"/decision-tree-findings/{finding['code']}", body
        )
        print(f"{status} finding {finding['code']}")
        failed += status != 200
    status, text = _call("GET", "/platform/decision-trees/beta")
    if status != 200:
        print(f"list failed: {status} {text}")
        return 1
    ids = {t["code"]: t["id"] for t in json.loads(text)}
    for path in sorted(TREES.glob("*.definition.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        tree_id = ids.get(definition["code"])
        if tree_id is None:
            print(f"missing tree {definition['code']}")
            failed += 1
            continue
        body = json.dumps(
            {
                "definition": definition,
                "notes": "Arabic from the manual's Arabic edition. Draft, not published.",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, text = _call(
            "POST", f"/platform/decision-trees/beta/{tree_id}/versions", body
        )
        print(f"{status} tree {definition['code']}")
        if status not in (200, 201):
            print(text)
            failed += 1
    return 1 if failed else 0


def main() -> int:
    if not API or not TOKEN:
        print("Set AGRIPULSE_API and AGRIPULSE_TOKEN.")
        return 2
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "archive-old":
        return archive_old(dry_run="--dry-run" in sys.argv)
    if command == "create":
        return create()
    if command == "update":
        return update()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
