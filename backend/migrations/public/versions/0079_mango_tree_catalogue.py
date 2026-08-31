"""Retire the mango trees the T_ catalogue replaces, and add the harvest group.

The 2026-08 mango index guide (`tatoo Docs/Mango indices- 28_8/
AgriPulse_Mango_Indices_Plan_EN.xlsx`) is a rewrite of the workbook the
earlier mango rules were built from, and it ships something the earlier one
did not have: a stage-by-stage agriculture plan. Twenty-two decision trees,
all coded `t_*`, now carry the whole file — eleven for the index bands, five
that read several indices together, six from the plan sheets.

Nine of them cover ground a shipped tree already covered. Two trees answering
the same question on the same block open two cards for one problem, so the
seed files are deleted in the same change and the platform rows are retired
here:

  mango_canopy_vigour_by_size_v1    -> t_ndvi / t_evi / t_savi / t_msavi
  mango_canopy_moisture_by_size_v1  -> t_ndmi_leaf_water
  mango_canopy_cover_gap_v1         -> t_bsi_ground_cover
  mango_post_harvest_nitrogen_v1    -> t_ndre_nitrogen
  mango_powdery_mildew_risk_v1      -> t_bloom_protection
  mango_anthracnose_risk_v1         -> t_anthracnose_mealybug_watch
  mango_fruit_fly_risk_v1           -> t_fruit_fly_harvest_readiness
  mango_stress_induction_v1         -> t_flower_induction_readiness

Each replacement is a superset, not a rename. The four vigour trees split what
was one tree so the index matches the size, as the guide's own advice says it
should. The three weather-risk trees gain the plan's stage gate and its
instructions: the mildew tree now carries the pollinator constraint that makes
a bloom-time spray safe, and the fruit fly tree carries the selective-picking
and hot-water-treatment steps. The induction tree gains the flush
precondition, without which the dry period is started into growing shoots and
the season is lost.

`mango_canopy_health_v1` and `ndvi_baseline_alert_v1` are deliberately KEPT.
Both judge a block against its own history rather than against an absolute
band, which is a different question, and the guide's own limits are the reason
to keep both kinds: it states that no published study measures these indices
for these nine varieties, so an absolute band alone is thin evidence.

Retiring is `is_active = FALSE`, which is what the admin screens' delete does.
The rows stay, their versions stay, and every recommendation that cites one
stays explainable. `sync_from_disk` only ever touches a tree whose YAML is on
disk, so a retired row with no file stays retired across restarts.

Open cards from the retired trees are left alone on purpose. They are real
findings that a person may already be acting on, and closing someone else's
work queue from a migration is not this change's business.

The one genuinely new field is `harvest_season_group`. The new workbook
groups the nine varieties into four harvest windows that differ by months --
Sukkary from late May, Keitt into November -- and states that it found no
source for any difference in the PRACTICES between them, only in the timing.
Nothing in the platform records which group a block belongs to. `tree_size_class`
and `bearing_status` already exist at the `mango` path (migration 0072) with
exactly the vocabulary the new sheet uses, so they are reused rather than
duplicated; adding a second size field is the mistake 0072 was written to
undo.

Revision ID: 0079
Revises: 0078
Create Date: 2026-08-31
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SUPERSEDED: tuple[str, ...] = (
    "mango_canopy_vigour_by_size_v1",
    "mango_canopy_moisture_by_size_v1",
    "mango_canopy_cover_gap_v1",
    "mango_post_harvest_nitrogen_v1",
    "mango_powdery_mildew_risk_v1",
    "mango_anthracnose_risk_v1",
    "mango_fruit_fly_risk_v1",
    "mango_stress_induction_v1",
)

_GROUP = ("canopy", "Canopy & bearing", "المجموع والإثمار")


def _opt(code: str, en: str, ar: str, order: int) -> dict[str, Any]:
    return {"code": code, "name_en": en, "name_ar": ar, "sort_order": order}


# The four groups and their varieties are the workbook's own, and so is the
# fourth one's name. It found no variety-specific harvest-timing source for
# Crimson, Yasmeena or Zebdia and used the reference study's default June to
# September window as a placeholder, recommending field verification. Calling
# that group "confirmed" would launder a placeholder into a fact, so the
# option says what it is.
_HARVEST_GROUP: dict[str, Any] = {
    "code": "harvest_season_group",
    "name_en": "Harvest season group",
    "name_ar": "مجموعة موسم الحصاد",
    "description_en": (
        "Which harvest window this block's variety falls in. The index value "
        "ranges are identical across all nine mango varieties -- no published "
        "study separates them -- but the harvest timing is not: Sukkary starts "
        "in late May while Keitt can still be picked in November. The plan "
        "rules read this to place the harvest and post-harvest windows."
    ),
    "description_ar": (
        "في أي نافذة حصاد يقع صنف هذه القطعة. نطاقات قيم المؤشرات واحدة في "
        "الأصناف التسعة كلها — إذ لا توجد دراسة منشورة تفرّق بينها — أما توقيت "
        "الحصاد فمختلف: يبدأ السكري في أواخر مايو بينما قد يُجنى كيت حتى "
        "نوفمبر. تقرأ قواعد الخطة هذه القيمة لتحديد نافذتي الحصاد وما بعده."
    ),
    "value_type": "single_select",
    "options": [
        _opt(
            "early",
            "Early — Sukkary, Alphonso (late May to August)",
            "مبكرة — سكري، ألفونسو (أواخر مايو حتى أغسطس)",
            1,
        ),
        _opt(
            "mid",
            "Mid — Ewais, Osteen, Kent (July to September)",
            "متوسطة — عويس، أوستين، كنت (يوليو حتى سبتمبر)",
            2,
        ),
        _opt(
            "late",
            "Late — Keitt (August to November)",
            "متأخرة — كيت (أغسطس حتى نوفمبر)",
            3,
        ),
        _opt(
            "unconfirmed",
            "Timing not confirmed — Crimson, Yasmeena, Zebdia (June to September, default)",
            "توقيت غير مؤكد — كريمسون، ياسمينا، زبدية (يونيو حتى سبتمبر، افتراضي)",
            4,
        ),
    ],
    "is_required": False,
    "sort_order": 3,
}

_COLUMNS = (
    "crop_id, crop_variety_id, crop_variety_strain_id, path, code, name_en, name_ar,"
    " description_en, description_ar, value_type, options, is_required, group_code,"
    " group_name_en, group_name_ar, sort_order, is_reportable"
)
_VALUES = (
    ":path, :code, :name_en, :name_ar, :description_en, :description_ar,"
    " :value_type, CAST(:options AS jsonb), :is_required, :group_code,"
    " :group_name_en, :group_name_ar, :sort_order, TRUE"
)

_INSERT = sa.text(
    f"INSERT INTO public.crop_attribute_definitions ({_COLUMNS}) "
    f"SELECT c.id, NULL, NULL, {_VALUES} "
    "FROM public.crops c WHERE c.code = 'mango' "
    "ON CONFLICT (path, code) DO NOTHING"
)
_DELETE_NEW = sa.text(
    "DELETE FROM public.crop_attribute_definitions WHERE path = 'mango' AND code = :code"
)

# `tenant_id IS NULL` keeps this to the platform catalog. A tenant that
# authored its own tree under one of these codes owns that row and this
# migration has no business touching it.
_RETIRE_TREES = sa.text(
    "UPDATE public.decision_trees SET is_active = FALSE, updated_at = now() "
    "WHERE tenant_id IS NULL AND deleted_at IS NULL AND code = ANY(:codes)"
)
_RESTORE_TREES = sa.text(
    "UPDATE public.decision_trees SET is_active = TRUE, updated_at = now() "
    "WHERE tenant_id IS NULL AND deleted_at IS NULL AND code = ANY(:codes)"
)


def upgrade() -> None:
    bind = op.get_bind()
    group_code, group_en, group_ar = _GROUP
    bind.execute(
        _INSERT,
        {
            "path": "mango",
            "code": _HARVEST_GROUP["code"],
            "name_en": _HARVEST_GROUP["name_en"],
            "name_ar": _HARVEST_GROUP["name_ar"],
            "description_en": _HARVEST_GROUP["description_en"],
            "description_ar": _HARVEST_GROUP["description_ar"],
            "value_type": _HARVEST_GROUP["value_type"],
            "options": json.dumps(_HARVEST_GROUP["options"]),
            "is_required": _HARVEST_GROUP["is_required"],
            "group_code": group_code,
            "group_name_en": group_en,
            "group_name_ar": group_ar,
            "sort_order": _HARVEST_GROUP["sort_order"],
        },
    )
    bind.execute(_RETIRE_TREES, {"codes": list(_SUPERSEDED)})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_RESTORE_TREES, {"codes": list(_SUPERSEDED)})
    bind.execute(_DELETE_NEW, {"code": _HARVEST_GROUP["code"]})
