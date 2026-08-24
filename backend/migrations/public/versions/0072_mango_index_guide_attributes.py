"""Mango crop attributes for the index guide: tree size and bearing status.

`tatoo Docs/AgriPulse_Mango_Indices_Full_EN.xlsx` keys every expected index
range on four axes. Three of them the platform already reads --
`growth_stage`, the index itself, and the crop -- and the fourth pair it does
not have at all:

* **tree size** (small / medium / big). The workbook's largest effect by far:
  NDVI runs 0.10-0.22 on a small tree and 0.65-0.81 on a big one, so a rule
  that does not know the size is comparing a sapling against an orchard.
  `block_crops.canopy_size_class` was built for exactly this and is still a
  validated column, but no screen ever writes it and it was dropped from the
  decision-tree field vocabulary for that reason. Reviving it needs frontend
  work; a crop attribute renders its own field, validates its own options and
  is already a condition source, so the axis lands here instead.
* **bearing status** (bearing / not bearing this season). Mango alternate
  bearing is the reason this axis exists: the same tree carries fruit one
  year and rests the next, and the workbook shifts the CWSI and SMI bands
  accordingly once the fruit is on.

The same migration retires five hand-authored `mango` definitions that were
created through the admin screens and now shadow each other:

  `001` "Tree Size"        multi-select, 0 values recorded
  `002` "Tree type"        multi-select, 0 values recorded
  `testyyy`                multi-select, 0 values recorded
  `003` "Tree size"        single-select, 153 values recorded
  `004` "Establish method" single-select, 153 values recorded

`001` and `003` are two size fields; `003` also folds bearing into the size
options ("Young non-productive" / "Young new-productive" / "Mature
productive"), which is why no rule can ask about size on its own. `004`
duplicates the curated `establishment_method` seeded in 0051. `002` restates
the grafted/seedling half of `004`.

Retiring is `is_active = FALSE`, which is what the admin screens' own delete
does -- the rows stay, so the recorded values stay readable and the step is
reversible. Tenant migration 0084 then copies the `003` and `004` values onto
the new definitions. Ordering is guaranteed by the deploy hook, which runs
`alembic -n public upgrade head` before `scripts.migrate_tenants`
(infra/helm/api/templates/migration-job.yaml), so the destinations exist
before any tenant reads them. The copy matches definitions by code and does
not filter on `is_active`, so retiring the sources here does not hide them
from it.

The curated `establishment_method` is **re-activated** here. Somebody had
retired it on prod, which was reasonable while `004` existed and shadowed it
-- but `004` is the copy that goes now, and establishment is one of the
workbook's own axes: its Varieties sheet turns on which cultivars can be
seed-propagated at all. Leaving it retired would hide the 153 values that
tenant migration 0084 copies into it and drop the axis entirely.

`tree_age` is left alone on purpose: 117 recorded values, not an axis in the
workbook, and it shadows nothing. `implantation_date` is retired in migration
0073, where its reason belongs -- it duplicates `block_crops.planting_date`,
and the two agree on 71 of the 72 rows on prod.

Revision ID: 0072
Revises: 0071
Create Date: 2026-08-23
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_GROUP = ("canopy", "Canopy & bearing", "المجموع والإثمار")

# Codes retired below, and the one re-activated. Every one is
# `path = 'mango'`. Three of the five are already inactive on prod; the
# UPDATE is safe to run more than once either way.
_RETIRED = ("001", "002", "003", "004", "testyyy")
_REACTIVATED = ("establishment_method",)


def _opt(code: str, en: str, ar: str, order: int) -> dict[str, Any]:
    return {"code": code, "name_en": en, "name_ar": ar, "sort_order": order}


# Size codes match `crops.size_classes` (migration 0033) so the two
# vocabularies cannot drift: small / medium / large. The workbook says
# "Big"; the catalog says "Large (>4 m)". Same class.
#
# Sukkary and Zebda carry a variety-level size list of medium / large /
# very_large. A very large Sukkary records as `large` here, which is the
# workbook's "Big" row -- the row it would have used anyway, since the
# workbook has no fourth size.
_TREE_SIZE: dict[str, Any] = {
    "code": "tree_size_class",
    "name_en": "Tree size",
    "name_ar": "حجم الشجرة",
    "description_en": (
        "Canopy size class of the trees in this block. Every expected index "
        "range is read against this -- a small tree over bright soil reads far "
        "lower than a closed canopy at the same health."
    ),
    "description_ar": (
        "فئة حجم مجموع الأشجار في هذه القطعة. تُقرأ كل النطاقات المتوقعة "
        "للمؤشرات مقابلها — الشجرة الصغيرة فوق تربة فاتحة تعطي قراءة أقل "
        "بكثير من مجموع مغلق بنفس الصحة."
    ),
    "value_type": "single_select",
    "options": [
        _opt("small", "Small (under 2 m)", "صغيرة (أقل من 2 م)", 1),
        _opt("medium", "Medium (2-4 m)", "متوسطة (2-4 م)", 2),
        _opt("large", "Large (over 4 m)", "كبيرة (أكثر من 4 م)", 3),
    ],
    "is_required": False,
    "sort_order": 1,
}

# Kept separate from size on purpose. The retired `003` merged the two, so
# "is this tree big?" could not be asked without also asserting it bears.
_BEARING: dict[str, Any] = {
    "code": "bearing_status",
    "name_en": "Bearing this season",
    "name_ar": "الإثمار هذا الموسم",
    "description_en": (
        "Whether these trees are carrying a crop this season. Mango alternate "
        "bearing means a mature tree rests in some years -- a resting tree runs "
        "cooler and wetter than a bearing one, so the irrigation-stress "
        "thresholds differ. This does not update on its own; edit it each "
        "season."
    ),
    "description_ar": (
        "هل تحمل هذه الأشجار محصولًا هذا الموسم. المعاومة في المانجو تعني أن "
        "الشجرة الناضجة ترتاح في بعض السنوات — والشجرة المرتاحة أبرد وأكثر "
        "رطوبة من المثمرة، لذا تختلف حدود إجهاد الريّ. لا تتحدث هذه القيمة "
        "تلقائيًا؛ عدّلها كل موسم."
    ),
    "value_type": "single_select",
    "options": [
        _opt("bearing", "Bearing (carrying fruit)", "مثمرة (تحمل ثمارًا)", 1),
        _opt("not_bearing", "Not bearing (young or resting)", "غير مثمرة (صغيرة أو مرتاحة)", 2),
    ],
    "is_required": False,
    "sort_order": 2,
}

_NEW: tuple[dict[str, Any], ...] = (_TREE_SIZE, _BEARING)


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

_RETIRE = sa.text(
    "UPDATE public.crop_attribute_definitions SET is_active = FALSE "
    "WHERE path = 'mango' AND code = ANY(:codes)"
)
_ACTIVATE = sa.text(
    "UPDATE public.crop_attribute_definitions SET is_active = TRUE "
    "WHERE path = 'mango' AND code = ANY(:codes)"
)
_DEACTIVATE = sa.text(
    "UPDATE public.crop_attribute_definitions SET is_active = FALSE "
    "WHERE path = 'mango' AND code = ANY(:codes)"
)
_DELETE_NEW = sa.text(
    "DELETE FROM public.crop_attribute_definitions WHERE path = 'mango' AND code = ANY(:codes)"
)


def upgrade() -> None:
    bind = op.get_bind()
    group_code, group_en, group_ar = _GROUP
    for definition in _NEW:
        bind.execute(
            _INSERT,
            {
                "path": "mango",
                "code": definition["code"],
                "name_en": definition["name_en"],
                "name_ar": definition["name_ar"],
                "description_en": definition["description_en"],
                "description_ar": definition["description_ar"],
                "value_type": definition["value_type"],
                "options": json.dumps(definition["options"], ensure_ascii=False),
                "is_required": definition["is_required"],
                "group_code": group_code,
                "group_name_en": group_en,
                "group_name_ar": group_ar,
                "sort_order": definition["sort_order"],
            },
        )
    bind.execute(_RETIRE, {"codes": list(_RETIRED)})
    bind.execute(_ACTIVATE, {"codes": list(_REACTIVATED)})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_DEACTIVATE, {"codes": list(_REACTIVATED)})
    bind.execute(_ACTIVATE, {"codes": list(_RETIRED)})
    bind.execute(_DELETE_NEW, {"codes": [d["code"] for d in _NEW]})
