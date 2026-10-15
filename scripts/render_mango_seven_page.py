"""Regenerate the proposal page's tree table from the definitions that shipped.

The page was written before the trees were built, and building them changed
six things: EVI was dropped, two finding codes turned out not to be needed,
four anthracnose-and-mildew rules were missing, and the API refuses a clause
containing a comma. Rather than edit the page by hand and let it drift again,
this reads docs/trees/mango_seven/*.definition.json — the same files that were
posted to production — and rewrites the table, the counts and the catalogue
section from them.

Run after scripts/build_mango_seven.py.
"""

from __future__ import annotations

import html
import io
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TREES = ROOT / "docs" / "trees" / "mango_seven"
PAGE = ROOT / "docs" / "proposals" / "mango-tree-regrouping.html"

# One row of the table, in the order the page shows them. `covers` is the old
# trees this one replaces; `built` is what production holds.
ORDER = [
    (
        "mango_water",
        "Water and irrigation",
        [
            "t_cwsi_irrigation_stress",
            "t_smi_soil_moisture",
            "t_ndmi_leaf_water",
            "t_msi_moisture_stress",
            "t_water_stress_confirm",
            "t_deficit_irrigation_verify",
            "mango_canopy_moisture_by_size_v1",
        ],
        "01a0c607-db7e-7c58-9e3b-ac9690a432b6",
    ),
    (
        "mango_canopy_and_stand",
        "Canopy and stand",
        [
            "t_ndvi_canopy_vigour",
            "t_savi_canopy_vigour",
            "t_msavi_canopy_vigour",
            "t_evi_canopy_vigour",
            "t_vigour_cause_split",
            "t_bsi_ground_cover",
            "t_young_orchard_establishment",
            "mango_canopy_health_v1",
            "mango_canopy_vigour_by_size_v1",
            "mango_canopy_cover_gap_v1",
        ],
        "01a0c607-d38f-7075-8728-092c9a5430e4",
    ),
    (
        "mango_nutrition",
        "Feeding",
        ["t_ndre_nitrogen", "t_gndvi_chlorophyll", "mango_post_harvest_nitrogen_v1"],
        "01a0c607-d820-7bfb-9b7d-caad33326c2e",
    ),
    (
        "mango_pest_disease",
        "Pest and disease pressure",
        [
            "t_anthracnose_mealybug_watch",
            "t_bloom_protection",
            "mango_anthracnose_risk_v1",
            "mango_powdery_mildew_risk_v1",
            "mango_fruit_fly_risk_v1",
        ],
        "01a0c607-d94f-7882-994a-34db56efca97",
    ),
    (
        "mango_flowering_program",
        "Flowering and fruit program",
        [
            "t_flower_induction_readiness",
            "t_fruit_development_program",
            "mango_stress_induction_v1",
        ],
        "01a0c607-d5fe-7e00-b657-36bef15ab2fa",
    ),
    (
        "mango_harvest_post_harvest",
        "Harvest and post-harvest",
        ["t_fruit_fly_harvest_readiness", "t_post_harvest_care"],
        "01a0c607-d71e-7d0c-81c1-87e55ba8058e",
    ),
    (
        "mango_records",
        "Record check",
        ["t_size_record_check"],
        "01a0c607-da72-7046-a56b-4a3998e7ec21",
    ),
]

# The 15 codes the platform catalogue already held on 2026-09-21.
WAS_LIVE = {
    "block_declining",
    "chlorophyll_low",
    "cover_open",
    "dry",
    "dry_unconfirmed",
    "fly_high",
    "fly_med",
    "mildew_high",
    "mildew_med",
    "ndvi_low",
    "nutrient_low",
    "pest_high",
    "pest_med",
    "size_missing",
    "vigour_low",
}


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def load() -> dict[str, Any]:
    return {
        code: json.loads((TREES / f"{code}.definition.json").read_text(encoding="utf-8"))
        for code, _, _, _ in ORDER
    }


def findings_cell(tree: dict[str, Any], clauses: dict[str, str]) -> str:
    items = []
    for code in tree["registers"]:
        mark = "" if code in WAS_LIVE else ' <span class="new">NEW</span>'
        items.append(f"<li><code>{esc(code)}</code>{mark} {esc(clauses[code])}</li>")
    return '<ul class="tight">' + "".join(items) + "</ul>"


def rules_cell(tree: dict[str, Any]) -> str:
    items = []
    for combo in tree["combinations"]:
        codes = " + ".join(combo["codes"])
        status = combo["status"]
        action = combo["action_type"]
        sentence = combo["text_en"].split(". ")[0].rstrip(".")
        items.append(
            f'<li><span class="set">{esc(codes)}</span> '
            f'<span class="st {status}">{status}</span> {esc(action)}. '
            f"{esc(sentence)}.</li>"
        )
    return '<ul class="tight">' + "".join(items) + "</ul>"


def table_rows(trees: dict[str, Any], clauses: dict[str, str]) -> str:
    rows = []
    for code, title, covers, _tree_id in ORDER:
        tree = trees[code]
        covered = "<br>".join(covers) + f"<br><b>{len(covers)} trees</b>"
        rows.append(
            f"""
      <tr>
        <td class="name">{esc(title)}<span class="ref">{esc(code)} &middot; {tree['scope']}</span></td>
        <td class="desc">{esc(tree['description_en'])}</td>
        <td class="find">{findings_cell(tree, clauses)}</td>
        <td class="rules">{rules_cell(tree)}</td>
        <td class="deps">{covered}</td>
      </tr>"""
        )
    return "\n".join(rows)


def built_rows(trees: dict[str, Any], dry: dict[str, tuple[int, int, int]]) -> str:
    rows = []
    for code, _title, _covers, tree_id in ORDER:
        tree = trees[code]
        evaluated, carded, errored = dry[code]
        rows.append(
            f"""      <tr><td class="name">{esc(code)}</td>"""
            f"""<td class="state">{tree['scope']}</td>"""
            f"""<td class="state">{len(tree['nodes'])}</td>"""
            f"""<td class="state">{len(tree['registers'])}</td>"""
            f"""<td class="state">{len(tree['combinations'])}</td>"""
            f"""<td class="desc">{evaluated} cells, {carded} carded, {errored} errored</td>"""
            f"""<td class="doc">{esc(tree_id)}</td></tr>"""
        )
    return "\n".join(rows)


def main() -> None:
    trees = load()
    new_findings = json.loads((TREES / "findings.json").read_text(encoding="utf-8"))
    clauses = {f["code"]: f["clause_en"] for f in new_findings}
    # The clauses of the codes that were already live, as production holds them.
    clauses.update(
        {
            "dry": "leaf water is low",
            "vigour_low": "canopy vigour is below the band for this tree size",
            "block_declining": "the block as a whole is below its seasonal baseline",
            "cover_open": "more bare ground is showing than the guide expects",
            "nutrient_low": "leaf nitrogen is below the band",
            "chlorophyll_low": (
                "leaf chlorophyll is below the band and the leaves may be old or starved"
            ),
            "pest_high": "anthracnose pressure is high",
            "pest_med": "anthracnose pressure is building",
            "mildew_high": "powdery mildew pressure is high",
            "mildew_med": "powdery mildew pressure is rising while the block is in bloom",
            "fly_high": "fruit fly pressure is high",
            "fly_med": "fruit fly pressure is rising on ripening fruit",
            "size_missing": "tree size is not recorded so no index band could be checked",
        }
    )

    # Read from the dry run on Bashier Elkhier block-009 on 2026-09-21.
    dry = {
        "mango_water": (33, 0, 0),
        "mango_canopy_and_stand": (33, 0, 0),
        "mango_nutrition": (33, 33, 0),
        "mango_pest_disease": (33, 0, 0),
        "mango_flowering_program": (33, 0, 0),
        "mango_harvest_post_harvest": (33, 33, 0),
        "mango_records": (33, 27, 0),
    }

    page = PAGE.read_text(encoding="utf-8")
    total_rules = sum(len(t["combinations"]) for t in trees.values())
    reused = sorted({c for t in trees.values() for c in t["registers"]} & WAS_LIVE)

    # counts
    page = re.sub(
        r'<div class="counts">.*?</div>\s*\n\s*<nav',
        f"""<div class="counts">
  <div class="count"><b>31</b><span>old mango trees</span></div>
  <div class="count"><b>7</b><span>trees built</span></div>
  <div class="count"><b>{total_rules}</b><span>combination rules</span></div>
  <div class="count"><b>{len(reused)}</b><span>catalogue codes reused</span></div>
  <div class="count"><b>{len(new_findings)}</b><span>new codes added</span></div>
  <div class="count"><b>0</b><span>cells errored</span></div>
</div>

<nav""",
        page,
        flags=re.S,
    )

    # the tree table body
    page = re.sub(
        r'(<thead><tr><th>Tree</th>.*?<tbody>).*?(\n\s*</tbody>)',
        lambda m: m.group(1) + "\n" + table_rows(trees, clauses) + m.group(2),
        page,
        flags=re.S,
    )

    # the "built" section, inserted before the old-set section
    built = f"""<section id="built">
  <h2>What is in production <span class="tag">created 2026-09-21</span></h2>
  <p class="lede">All seven were created in the platform catalogue as beta trees, draft version 1. None is published. A beta tree carries stage beta and the nightly sweep reads stage live, so none of them runs on a schedule. The dry run below is one block, Bashier Elkhier block-009, 33 cells.</p>
  <div class="scroller">
  <table>
    <thead><tr><th>Tree</th><th>Scope</th><th>Nodes</th><th>Findings</th><th>Rules</th><th>Dry run</th><th>Id</th></tr></thead>
    <tbody>
{built_rows(trees, dry)}
    </tbody>
  </table>
  </div>
</section>

<section id="oldset">"""
    # Idempotent: drop any section this script inserted before, so a second
    # run rewrites it instead of adding a second copy.
    page = re.sub('<section id="built">.*?</section>' + chr(10) + chr(10), "", page, flags=re.S)
    page = page.replace('<section id="oldset">', built, 1)

    PAGE.write_text(page, encoding="utf-8", newline="\n")
    print(f"rewrote {PAGE.name}: {total_rules} rules, {len(new_findings)} new codes")


if __name__ == "__main__":
    main()
