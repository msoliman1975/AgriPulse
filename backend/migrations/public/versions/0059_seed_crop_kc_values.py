"""Seed FAO-56 crop coefficients into `crops.phenology_stages`.

``irrigation.engine.lookup_kc`` has always preferred a per-stage ``kc`` field
on the crop's phenology JSONB, falling back to a code-level table. No seed ever
wrote that field, so the fallback was doing all the work — and the fallback is
keyed on a stage vocabulary the catalog does not use:

    _DEFAULT_KC_BY_STAGE   germination, vegetative, flowering, fruit_set,
                           fruit_development, maturity, ripening, senescence
    mango       (0033)     pre_flowering, flowering, fruit_set,
                           fruit_development, maturation, post_harvest_flush
    potato      (0033)     emergence, vegetative, tuber_initiation,
                           tuber_bulking, maturation
    date_palm   (0038)     fruit_set, kimri, khalal, rutab

Three of mango's six stages match, two of potato's five, and none of date
palm's four. Every other block-day resolved to the generic 0.85 bucket — so the
irrigation recommendation has effectively been running on a constant, and the
new per-block water balance would have inherited the same flaw.

**Provenance.** The anchors are FAO-56 Table 12 single crop coefficients:

    mango       Kc_ini 0.25   Kc_mid 0.90   Kc_end 0.75
    potato      Kc_ini 0.50   Kc_mid 1.15   Kc_end 0.75
    date palm   Kc_ini 0.90   Kc_mid 0.95   Kc_end 0.95

Placing each catalogued stage on the ini → mid → end curve is OUR reading, not
FAO's — FAO-56 defines a four-stage length curve, not these phenology codes.
The endpoints are citable; the intermediate placements are a defensible
interpretation that an agronomist should confirm before anyone treats an
irrigation figure as authoritative. That is why the values land in the catalog
JSONB, which an agronomist can edit per crop, variety or strain without a
migration, rather than being hardcoded.

Mango's `pre_flowering` is deliberately the lowest point of its curve: that
stage is the stress-induction period (0033 names it "التصويم"), where water is
withheld ON PURPOSE to trigger flowering. A Kc that ignored this would have
the system recommending irrigation precisely when the grower is withholding it.

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-12
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# crop code -> {stage code: Kc}. See the module docstring for provenance.
_KC_BY_CROP_STAGE: dict[str, dict[str, str]] = {
    "mango": {
        # Stress induction — water withheld deliberately. Near Kc_ini.
        "pre_flowering": "0.35",
        "flowering": "0.65",
        "fruit_set": "0.80",
        # Peak canopy demand — Kc_mid.
        "fruit_development": "0.90",
        "maturation": "0.85",
        # Kc_end; the tree is still evergreen, so it never drops to Kc_ini.
        "post_harvest_flush": "0.75",
        "veg_flush": "0.75",
    },
    "potato": {
        "emergence": "0.50",  # Kc_ini
        "vegetative": "0.80",  # development
        "tuber_initiation": "1.05",
        "tuber_bulking": "1.15",  # Kc_mid
        "maturation": "0.75",  # Kc_end
    },
    "date_palm": {
        # Date palm barely varies across the season — an evergreen with a
        # near-constant canopy — which is why FAO's three anchors sit within
        # 0.05 of each other rather than spanning a range like potato's.
        "fruit_set": "0.90",
        "kimri": "0.95",
        "khalal": "0.95",
        "rutab": "0.95",
    },
}


def _apply(stages_doc: Any, kc_by_stage: dict[str, str]) -> tuple[Any, int]:
    """Merge `kc` into each stage entry by code. Returns (doc, n_updated).

    Tolerates both catalog shapes `_phenology_kc` accepts: `stages` as a list
    of dicts, or as a dict keyed by stage code.
    """
    if not isinstance(stages_doc, dict):
        return stages_doc, 0
    raw = stages_doc.get("stages")
    updated = 0

    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code") or entry.get("name")
            if code in kc_by_stage and "kc" not in entry:
                entry["kc"] = kc_by_stage[code]
                updated += 1
    elif isinstance(raw, dict):
        for code, entry in raw.items():
            if isinstance(entry, dict) and code in kc_by_stage and "kc" not in entry:
                entry["kc"] = kc_by_stage[code]
                updated += 1

    return stages_doc, updated


def upgrade() -> None:
    bind = op.get_bind()
    select = sa.text("SELECT phenology_stages FROM public.crops WHERE code = :code")
    update = sa.text(
        "UPDATE public.crops SET phenology_stages = CAST(:doc AS jsonb) WHERE code = :code"
    )

    for crop_code, kc_by_stage in _KC_BY_CROP_STAGE.items():
        row = bind.execute(select, {"code": crop_code}).first()
        # A crop absent from this deployment is not an error — the seeds that
        # created them are separate migrations and a tenant may not run all.
        if row is None or row[0] is None:
            continue
        doc, updated = _apply(row[0], kc_by_stage)
        if updated:
            bind.execute(update, {"code": crop_code, "doc": json.dumps(doc)})


def downgrade() -> None:
    """Strip the `kc` keys this migration added, leaving the rest intact."""
    bind = op.get_bind()
    select = sa.text("SELECT phenology_stages FROM public.crops WHERE code = :code")
    update = sa.text(
        "UPDATE public.crops SET phenology_stages = CAST(:doc AS jsonb) WHERE code = :code"
    )

    for crop_code, kc_by_stage in _KC_BY_CROP_STAGE.items():
        row = bind.execute(select, {"code": crop_code}).first()
        if row is None or not isinstance(row[0], dict):
            continue
        doc = row[0]
        raw = doc.get("stages")
        entries: list[Any] = []
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = list(raw.values())
        for entry in entries:
            if isinstance(entry, dict) and entry.get("code") in kc_by_stage:
                entry.pop("kc", None)
        bind.execute(update, {"code": crop_code, "doc": json.dumps(doc)})
