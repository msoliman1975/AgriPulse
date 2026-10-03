"""Start date palm from a clean state before the organic Medjool seed.

The Organic Medjool Manual (Edition 1.3, September 2026) replaces what was
seeded for date palm in 0039 and 0042. Three things go:

* **The 7 date palm plan templates** (``datepalm-<cultivar>-eg``, 0042). They
  use ammonium sulphate, calcium superphosphate and abamectin, none of which
  the manual names and none of which an organic plan may use. They are
  deleted, with their activities (ON DELETE CASCADE). Tenant plans keep their
  activities: ``applied_template_id`` is a logical reference, not a foreign
  key, so no applied plan is touched.
* **The variety calendars** (0039 gave Medjool and Siwi a "dry cultivar"
  calendar that runs 5-9 weeks later than the manual). Every date palm
  variety is reset to code and names only, so it falls back to the crop
  calendar. 0097 then gives Medjool its own calendar from the manual.
* **The crop depth.** Production holds ``date_palm`` at ``crop_only``, because
  0030 promoted only crops that already had varieties and the date palm
  varieties arrived later, in 0039. At ``crop_only`` a block stores the path
  ``date_palm`` and nothing aimed at ``date_palm.medjool`` can reach it.

No production tenant had a date palm block when this was written (0 rows in
4 tenant schemas), so no farm changes.

The old decision trees are not touched here. Trees live in the database and
are managed in the app since 0085; they are archived through the app.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0096"
down_revision: str | Sequence[str] | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TEMPLATES = [
    "datepalm-zaghloul-eg",
    "datepalm-samany-eg",
    "datepalm-hayany-eg",
    "datepalm-amhat-eg",
    "datepalm-siwi-eg",
    "datepalm-barhi-eg",
    "datepalm-medjool-eg",
]


def upgrade() -> None:
    conn = op.get_bind()

    deleted = conn.execute(
        sa.text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))
        ),
        {"codes": _OLD_TEMPLATES},
    ).rowcount

    conn.execute(
        sa.text(
            "UPDATE public.crop_varieties SET "
            " phenology_stages_override = NULL, "
            " size_classes_override = NULL "
            "WHERE crop_id = (SELECT id FROM public.crops "
            "                 WHERE code = 'date_palm' AND deleted_at IS NULL)"
        )
    )

    conn.execute(
        sa.text(
            "UPDATE public.crops SET classification_depth = 'variety' "
            "WHERE code = 'date_palm' AND deleted_at IS NULL"
        )
    )
    print(f"0096: date palm templates deleted={deleted}")


def downgrade() -> None:
    # The deleted templates and the dry-cultivar calendars are not restored:
    # they contradict the organic manual this revision exists for. Re-run
    # 0039 and 0042 by hand if they are ever needed again. Only the depth
    # change is reversible without loss.
    op.get_bind().execute(
        sa.text(
            "UPDATE public.crops SET classification_depth = 'crop_only' "
            "WHERE code = 'date_palm' AND deleted_at IS NULL"
        )
    )
