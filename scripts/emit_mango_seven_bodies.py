"""Write the request bodies scripts/create-mango-seven.ps1 posts, byte for byte.

PowerShell reads a JSON file into objects and serialises it again on the way
out, and that round trip double-encodes Arabic without reporting anything: the
call returns 200 and the stored text is wrong. So the body is built here, in
Python, and the PowerShell script posts the file's raw bytes without looking
inside. See feedback_powershell_mangles_utf8_on_api_round_trip.

Run scripts/build_mango_seven.py first; this reads what it wrote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "docs" / "trees" / "mango_seven"
BODIES = OUT / "bodies"

NOTES = "Seven mango trees by agronomy area, from docs/proposals/mango-tree-regrouping.html"


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> None:
    BODIES.mkdir(parents=True, exist_ok=True)
    codes = []
    for path in sorted(OUT.glob("*.definition.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        code = definition["code"]
        codes.append(code)
        write_json(
            BODIES / f"create.{code}.json",
            {"code": code, "definition": definition, "notes": NOTES},
        )
        write_json(
            BODIES / f"version.{code}.json",
            {"definition": definition, "notes": NOTES},
        )
    for finding in json.loads((OUT / "findings.json").read_text(encoding="utf-8")):
        write_json(BODIES / f"finding.{finding['code']}.json", finding)
    write_json(BODIES / "index.json", {"trees": codes})
    print(f"{len(codes)} trees and their bodies written to {BODIES}")


if __name__ == "__main__":
    main()
