"""Seed a published mango stage-anchored starter plan template (PR-E5).

Exercises all three activity anchors against the seeded mango phenology
(migration 0033, crop-level calendar_doy stages):
  * start-anchored land prep (offset 0),
  * milestone-anchored irrigation setup,
  * stage-anchored post-harvest nitrogen flush (post_harvest_flush),
    pre-flowering irrigation withholding (pre_flowering), and
    fruit-development fertigation (fruit_development).

Idempotent: skips entirely if a template with the same code already exists,
so re-running the migration (or applying it after a manual seed) is a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "mango-season-eg"

_MILESTONES = [
    # code, name, day_from_start, sort_order
    ("irrigation_setup", "Irrigation setup", 14, 0),
]

# activity_type, anchor, milestone_code, stage_code, offset, duration,
# product_name, notes, sort_order
_ACTIVITIES = [
    (
        "soil_prep",
        "start",
        None,
        None,
        0,
        3,
        None,
        "Pre-season land preparation and basin maintenance.",
        1,
    ),
    (
        "irrigation",
        "milestone",
        "irrigation_setup",
        None,
        0,
        1,
        None,
        "Commission and pressure-test the drip lines for the season.",
        2,
    ),
    (
        "irrigation",
        "stage",
        None,
        "pre_flowering",
        0,
        1,
        None,
        "Withhold irrigation to induce flowering (water stress).",
        3,
    ),
    (
        "fertilizing",
        "stage",
        None,
        "fruit_development",
        0,
        1,
        "NPK 12-12-17 + K",
        "Fruit-development fertigation to support sizing.",
        4,
    ),
    (
        "fertilizing",
        "stage",
        None,
        "post_harvest_flush",
        7,
        1,
        "Urea (nitrogen)",
        "Post-harvest nitrogen flush to rebuild canopy reserves.",
        5,
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        text("SELECT id FROM public.plan_templates WHERE code = :c"), {"c": _CODE}
    ).scalar()
    if existing is not None:
        return  # already seeded -> idempotent no-op

    crop_id = bind.execute(
        text("SELECT id FROM public.crops WHERE code = 'mango' AND deleted_at IS NULL")
    ).scalar()

    template_id = bind.execute(
        text(
            "INSERT INTO public.plan_templates "
            "(code, name, crop_path, crop_id, country, region, description, status) "
            "VALUES (:code, :name, 'mango', :crop_id, 'EG', NULL, :descr, 'published') "
            "RETURNING id"
        ),
        {
            "code": _CODE,
            "name": "Mango season (Egypt)",
            "crop_id": crop_id,
            "descr": (
                "Starter season plan for Egyptian mango. Land prep + irrigation "
                "setup anchor to the season start; flowering, fruit-development and "
                "post-harvest tasks anchor to the tree's phenology stages."
            ),
        },
    ).scalar_one()

    milestone_ids: dict[str, str] = {}
    for code, name, day, sort_order in _MILESTONES:
        mid = bind.execute(
            text(
                "INSERT INTO public.plan_template_milestones "
                "(template_id, code, name, day_from_start, sort_order) "
                "VALUES (:tid, :code, :name, :day, :sort) RETURNING id"
            ),
            {"tid": template_id, "code": code, "name": name, "day": day, "sort": sort_order},
        ).scalar_one()
        milestone_ids[code] = mid

    for (
        activity_type,
        anchor,
        milestone_code,
        stage_code,
        offset_days,
        duration_days,
        product_name,
        notes,
        sort_order,
    ) in _ACTIVITIES:
        bind.execute(
            text(
                "INSERT INTO public.plan_template_activities "
                "(template_id, activity_type, anchor, milestone_id, stage_code, "
                " offset_days, duration_days, product_name, notes, sort_order) "
                "VALUES (:tid, :atype, :anchor, :milestone_id, :stage_code, "
                " :offset, :duration, :product, :notes, :sort)"
            ),
            {
                "tid": template_id,
                "atype": activity_type,
                "anchor": anchor,
                "milestone_id": milestone_ids.get(milestone_code) if milestone_code else None,
                "stage_code": stage_code,
                "offset": offset_days,
                "duration": duration_days,
                "product": product_name,
                "notes": notes,
                "sort": sort_order,
            },
        )


def downgrade() -> None:
    # Cascade removes milestones + activities. Data-safe: only the seeded row.
    op.get_bind().execute(text("DELETE FROM public.plan_templates WHERE code = :c"), {"c": _CODE})
