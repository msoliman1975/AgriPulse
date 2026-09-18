"""Build the `mango_unified` beta tree from its design document.

`docs/proposals/mango-unified-tree.md` holds the tree in fenced YAML blocks,
one per section, and the finding catalogue as prose. That document is the
source of truth and stays readable; this script turns it into the two JSON
bodies the authoring API takes:

    docs/trees/mango_unified.definition.json   POST .../decision-trees/beta
    docs/trees/mango_unified.findings.json     POST .../decision-tree-findings

Run it after editing the document, and commit what it writes:

    python scripts/build_mango_unified.py

It validates what it builds with the real compiler
(`app.modules.recommendations.folding_compiler`), so a document that has
drifted out of shape fails here rather than at the API.

Two combination rules are added here rather than in the document, both from
`Unification model.pdf`, and both marked in `ADDED_RULES` below with the
reason. Everything else comes from the document unchanged.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "proposals" / "mango-unified-tree.md"
OUT_DIR = ROOT / "docs" / "trees"

# The document's YAML blocks, in the order `re.findall` meets them.
BLOCK_EXAMPLE = 0  # the `set` example in section 1, not part of the tree
BLOCK_PARAMETERS = 1
BLOCK_HEADER = 2
BLOCK_NODES = (3, 4, 5, 6, 7, 8)
BLOCK_COMBINATIONS = 9


def yaml_blocks(text: str) -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", text, re.S)


def fix_on_key(obj: Any) -> Any:
    """Put back the `on` key that a YAML 1.1 loader reads as the boolean True.

    `switch: {on: ...}` is the shape the engine reads. PyYAML follows YAML 1.1,
    where a bare `on` is a boolean, so `switch.on` arrives as `True` and the
    compiler reports "a switch with nothing to switch on". js-yaml, which the
    designer uses, follows YAML 1.2 and keeps the string, and the stored
    definition is JSON, so this only bites a Python reader of the document.
    """
    if isinstance(obj, dict):
        return {("on" if key is True else key): fix_on_key(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [fix_on_key(item) for item in obj]
    return obj


def build_definition(text: str) -> dict[str, Any]:
    blocks = yaml_blocks(text)
    header = yaml.safe_load(blocks[BLOCK_HEADER].replace("parameters: # see section 4.2\n", ""))
    parameters = yaml.safe_load(blocks[BLOCK_PARAMETERS])
    nodes = yaml.safe_load("\n".join(blocks[i] for i in BLOCK_NODES))
    combinations = yaml.safe_load(blocks[BLOCK_COMBINATIONS])
    definition = {**header, **parameters, "nodes": nodes, **combinations}
    definition["combinations"] = list(definition["combinations"]) + ADDED_RULES
    return fix_on_key(definition)


def build_findings(text: str) -> list[dict[str, Any]]:
    """The 14 catalogue rows, read out of section 2 and section 2.1.

    `action_type` is in the document's table and is deliberately not carried
    here: `decision_tree_findings` has no such column. A card's action type
    comes from the combination rule that matched.
    """
    table = text[text.index("| code | default_status") : text.index("### 2.1")]
    status_by_code = {
        match.group(1): match.group(2)
        for match in re.finditer(r"\|\s*`([a-z_]+)`\s*★?\s*\|\s*`([a-z_]+)`\s*\|", table)
    }

    section = text[text.index("### 2.1 Names and clauses") : text.index("## 3. How the composed")]
    rows: list[dict[str, Any]] = []
    for block in re.split(r"\n\*\*`", section)[1:]:
        code = block[: block.index("`")]
        name_en, name_ar = (
            part.strip() for part in block.splitlines()[0].split("—", 1)[1].split("/", 1)
        )
        rows.append(
            {
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "clause_en": re.search(r"clause_en: (.+)", block).group(1).strip(),
                "clause_ar": re.search(r"clause_ar: (.+)", block).group(1).strip(),
                "default_status": status_by_code[code],
            }
        )
    return rows


# --- The two rules that come from the PDF rather than the document ---------
#
# The PDF's Layer 2 tree ends with two steps the document's rule set does not
# cover. Both are about the same thing: never leave a card saying "it could be
# anything".
ADDED_RULES: list[dict[str, Any]] = [
    {
        # PDF step 7, `leaf_unseparated`. Without this rule a lone `vigour_low`
        # composes to its catalogue clause and the farmer reads a measurement
        # with no instruction. The rule says what is known and what is not.
        "codes": ["vigour_low"],
        "action_type": "scout",
        "status": "issue",
        "text_en": (
            "Canopy vigour is below the band for this tree size and nothing else measured here "
            "explains it. Water, red-edge, ground cover and the pest scores all read normal. "
            "This is the case that needs eyes on the tree: check the trunk and the roots and ask "
            "about salinity in the irrigation water."
        ),
        "text_ar": (
            "حيوية المجموع دون النطاق المتوقع لهذا الحجم ولا يوجد قياس آخر هنا يفسّر ذلك. "
            "الماء والحافة الحمراء وغطاء الأرض ودرجات الآفات كلها طبيعية. "
            "هذه هي الحالة التي تحتاج معاينة على الأرض: افحص الجذع والجذور واسأل عن ملوحة ماء الري."
        ),
    },
    {
        # PDF step 6, the named disease. This mirrors `{vigour_low, pest_high}`,
        # which the document already carries. Section 6.2 rejects
        # `{fly_high, vigour_low}` because fruit fly and canopy vigour share no
        # cause; powdery mildew does share one, because it takes the leaves and
        # the panicles, so the pairing earns a rule where fruit fly does not.
        "codes": ["vigour_low", "mildew_high"],
        "action_type": "spray",
        "status": "alert",
        "text_en": (
            "Canopy vigour dropped while powdery mildew pressure is high during bloom. Treat now "
            "and spray outside peak pollinator hours. Mango sets its crop through flies and bees "
            "and fruit lost to a badly timed spray does not come back."
        ),
        "text_ar": (
            "هبطت حيوية المجموع وضغط البياض الدقيقي مرتفع أثناء التزهير. عالج الآن ورُشّ خارج "
            "ساعات نشاط الملقّحات. تعقد المانجو محصولها بالذباب والنحل والثمار التي تُفقد برشّ "
            "سيئ التوقيت لا تعود."
        ),
    },
]


def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.modules.recommendations.folding_compiler import check_folding_tree

    text = DOC.read_text(encoding="utf-8")
    definition = build_definition(text)
    findings = build_findings(text)

    catalogue_codes = {row["code"] for row in findings}
    declared = set(definition["registers"])
    if declared != catalogue_codes:
        print(f"registers and catalogue disagree: {declared ^ catalogue_codes}")
        return 1

    errors = check_folding_tree(definition, known_codes=catalogue_codes)
    for error in errors:
        print(f"{error.rule} {error.node_ids}: {error.message_en}")
    if errors:
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "mango_unified.definition.json").write_text(
        json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "mango_unified.findings.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"ok: {len(definition['nodes'])} nodes, "
        f"{len(definition['registers'])} registers, "
        f"{len(definition['combinations'])} combination rules, "
        f"{len(definition['parameters'])} parameters, "
        f"{len(findings)} catalogue rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
