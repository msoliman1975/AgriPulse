"""Give mango a maturation stage, and retire three catalogue entries.

## The maturation stage

Migration 0033 gave mango six stages and no maturity: `fruit_development`
ran 1 May - 15 July and `post_harvest_flush` picked up on 16 July and ran to
31 October. Egyptian mango is harvested across July, August and September, so
that arrangement calls the whole harvest "post-harvest" and has no stage at
all for fruit hanging ripe on the tree.

Two things in the codebase were already written as if the stage existed:

* `0064_seed_crop_kc_values` seeds mango a Kc of 0.85 for `maturation`, and
  its docstring lists `maturation` among the stages 0033 supposedly created.
  That Kc row has been unreachable since it was written. It now resolves.
* The mango index guide (`tatoo Docs/AgriPulse_Mango_Indices_Full_EN.xlsx`)
  keys its CWSI and SMI bands on a "Maturity/Harvest" phase that had nothing
  to map onto. The held CWSI tree now gates on this stage.

The code is `maturation`, matching the Kc seed and potato's own stage of the
same name, not `maturity`.

Windows are set from the Egyptian harvest calendar rather than copied from
the workbook. The workbook's phase C opens on 8 June, but its phenology
source is a Sentinel-2 study in Ghana; Egyptian commercial harvest runs from
early July (Sukkary, Zebda) through September, with the late cultivars into
October. So the generic curve gives fruit development the whole of May and
June and opens maturation on 1 July:

    pre_flowering       12-01 - 01-31   unchanged
    flowering           02-01 - 03-15   unchanged
    fruit_set           03-16 - 04-30   unchanged
    fruit_development   05-01 - 06-30   was 05-01 - 07-15
    maturation          07-01 - 09-15   NEW
    post_harvest_flush  09-16 - 11-15   was 07-16 - 10-31
    veg_flush           11-16 - 11-30   was 11-01 - 11-30

Keitt keeps its own late-season override. It flowers a fortnight later and
is picked in September and October, so its maturation sits two months behind
the generic one and its post-harvest flush is compressed against winter:

    pre_flowering       12-15 - 02-15   unchanged
    flowering           02-16 - 03-31   unchanged
    fruit_set           04-01 - 05-15   unchanged
    fruit_development   05-16 - 08-15   was 05-16 - 09-15
    maturation          08-16 - 10-31   NEW
    post_harvest_flush  11-01 - 11-30   was 09-16 - 11-30
    veg_flush           12-01 - 12-14   unchanged

Both curves stay contiguous and cover all 12 months, which is what the daily
auto-advance task needs to always resolve a stage.

Nothing that reads a stage code breaks: every existing code survives. The
two plan templates that anchor activities (`0035`, `0040`) use
`fruit_development` and `post_harvest_flush`, which both still exist; their
resolved dates move, which is the point. Two disease models are widened in
the same change (`app/modules/weather/risk/models.py`) because fruit fly and
anthracnose do their damage on ripening fruit, and without `maturation` in
their susceptible sets both scores would have collapsed exactly when the
fruit is most vulnerable.

Blocks currently reading `post_harvest_flush` in July or August advance to
`maturation` on the next daily sweep. `mango_post_harvest_nitrogen_v1` goes
quiet for them until 16 September, which is correct -- they are in harvest,
not rebuilding reserves.

## Retirements

`implantation_date` (mango crop attribute, 72 values) duplicates
`block_crops.planting_date`: on prod the two agree on 71 of the 72 rows. The
date is already recorded on the crop assignment, so retiring the attribute
loses nothing and removes one of two date fields asking the same question.
Retired with `is_active = FALSE`, the same soft retire the admin screens do.

`demo_cell_low_ndvi_v1` and `scout_for_stress_v1` are archived
(`deleted_at`). Their seed files are deleted in the same commit, which is
required rather than tidy: `sync_from_disk` looks up an existing tree with
`deleted_at IS NULL`, so a file left on disk would insert a fresh row on the
next boot and undo the archive.

* `demo_cell_low_ndvi_v1` targets mango, is cell-scoped, and fires on a
  hardcoded NDVI below 0.15. The index guide puts 0.10-0.22 as the *normal*
  band for a small mango tree, so on a young orchard it flags cells that are
  behaving exactly as expected.
* `scout_for_stress_v1` scouts on an NDVI z-score with its thresholds
  hardcoded at -0.5 and -1.5 rather than declared as tunable parameters. On
  a mango block it asks the same question as `mango_canopy_health_v1`, which
  uses a soil-aware index and a parameter. Crop-agnostic NDVI-drop coverage
  remains via `ndvi_baseline_alert_v1`, which raises an alert rather than a
  scouting card.

Revision ID: 0073
Revises: 0072
Create Date: 2026-08-23
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | Sequence[str] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stage(code: str, en: str, ar: str, order: int, start: str, end: str) -> dict[str, Any]:
    return {
        "code": code,
        "name_en": en,
        "name_ar": ar,
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


_PRE = ("Pre-flowering (stress induction)", "ما قبل التزهير (التصويم)")
_FLW = ("Flowering", "التزهير")
_SET = ("Fruit set", "العقد")
_DEV = ("Fruit development", "تطور الثمار")
_MAT = ("Maturation / harvest", "النضج والحصاد")
_PHF = ("Post-harvest flush", "النمو بعد الحصاد")
_VEG = ("Vegetative flush", "النمو الخضري")


_MANGO_STAGES_NEW = {
    "stages": [
        _stage("pre_flowering", *_PRE, 1, "12-01", "01-31"),
        _stage("flowering", *_FLW, 2, "02-01", "03-15"),
        _stage("fruit_set", *_SET, 3, "03-16", "04-30"),
        _stage("fruit_development", *_DEV, 4, "05-01", "06-30"),
        _stage("maturation", *_MAT, 5, "07-01", "09-15"),
        _stage("post_harvest_flush", *_PHF, 6, "09-16", "11-15"),
        _stage("veg_flush", *_VEG, 7, "11-16", "11-30"),
    ]
}

_KEITT_STAGES_NEW = {
    "stages": [
        _stage("pre_flowering", *_PRE, 1, "12-15", "02-15"),
        _stage("flowering", *_FLW, 2, "02-16", "03-31"),
        _stage("fruit_set", *_SET, 3, "04-01", "05-15"),
        _stage("fruit_development", *_DEV, 4, "05-16", "08-15"),
        _stage("maturation", *_MAT, 5, "08-16", "10-31"),
        _stage("post_harvest_flush", *_PHF, 6, "11-01", "11-30"),
        _stage("veg_flush", *_VEG, 7, "12-01", "12-14"),
    ]
}

# The 0033 curves, restored on downgrade.
_MANGO_STAGES_OLD = {
    "stages": [
        _stage("pre_flowering", *_PRE, 1, "12-01", "01-31"),
        _stage("flowering", *_FLW, 2, "02-01", "03-15"),
        _stage("fruit_set", *_SET, 3, "03-16", "04-30"),
        _stage("fruit_development", *_DEV, 4, "05-01", "07-15"),
        _stage("post_harvest_flush", *_PHF, 5, "07-16", "10-31"),
        _stage("veg_flush", *_VEG, 6, "11-01", "11-30"),
    ]
}

_KEITT_STAGES_OLD = {
    "stages": [
        _stage("pre_flowering", *_PRE, 1, "12-15", "02-15"),
        _stage("flowering", *_FLW, 2, "02-16", "03-31"),
        _stage("fruit_set", *_SET, 3, "04-01", "05-15"),
        _stage("fruit_development", *_DEV, 4, "05-16", "09-15"),
        _stage("post_harvest_flush", *_PHF, 5, "09-16", "11-30"),
        _stage("veg_flush", *_VEG, 6, "12-01", "12-14"),
    ]
}


_UPDATE_CROP = sa.text(
    "UPDATE public.crops SET phenology_stages = CAST(:stages AS jsonb) WHERE code = 'mango'"
)
_UPDATE_KEITT = sa.text(
    "UPDATE public.crop_varieties v SET phenology_stages_override = CAST(:stages AS jsonb) "
    "FROM public.crops c WHERE c.id = v.crop_id AND c.code = 'mango' AND v.code = 'keitt'"
)

_SET_ATTRIBUTE_ACTIVE = sa.text(
    "UPDATE public.crop_attribute_definitions SET is_active = :active "
    "WHERE path = 'mango' AND code = 'implantation_date'"
)

_ARCHIVED_TREES = ("demo_cell_low_ndvi_v1", "scout_for_stress_v1")

# Platform trees only (`tenant_id IS NULL`). A tenant that authored its own
# tree under one of these codes is not this migration's business.
_ARCHIVE_TREES = sa.text(
    "UPDATE public.decision_trees SET deleted_at = now(), is_active = FALSE "
    "WHERE code = ANY(:codes) AND tenant_id IS NULL AND deleted_at IS NULL"
)
_RESTORE_TREES = sa.text(
    "UPDATE public.decision_trees SET deleted_at = NULL, is_active = TRUE "
    "WHERE code = ANY(:codes) AND tenant_id IS NULL"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(_UPDATE_CROP, {"stages": json.dumps(_MANGO_STAGES_NEW, ensure_ascii=False)})
    bind.execute(_UPDATE_KEITT, {"stages": json.dumps(_KEITT_STAGES_NEW, ensure_ascii=False)})
    bind.execute(_SET_ATTRIBUTE_ACTIVE, {"active": False})
    bind.execute(_ARCHIVE_TREES, {"codes": list(_ARCHIVED_TREES)})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_RESTORE_TREES, {"codes": list(_ARCHIVED_TREES)})
    bind.execute(_SET_ATTRIBUTE_ACTIVE, {"active": True})
    bind.execute(_UPDATE_KEITT, {"stages": json.dumps(_KEITT_STAGES_OLD, ensure_ascii=False)})
    bind.execute(_UPDATE_CROP, {"stages": json.dumps(_MANGO_STAGES_OLD, ensure_ascii=False)})
