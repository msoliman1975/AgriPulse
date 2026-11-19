"""How often a manual task repeats inside its window.

``plan_template_activities`` gains ``repeat_count`` and ``repeat_unit``
(``week`` | ``month`` | ``season``): the task is done ``repeat_count`` times
per unit across its window. Both null: once. A saved plan schedules each time
as its own task and board card (owner's decision, 2026-11-18).

Filled for the two Medjool 1.7 manuals from each task's "How often" line
(``data/0115_activity_repeat.json`` says how ranges were read). Mango and
potato manuals give no frequency, so their tasks stay single.

For a published manual this changes, the revision goes up and the published
snapshot takes the new values, as a publish would: farms with a saved plan see
"manual updated" listing the tasks that now repeat, and re-applying the plan
schedules each time. Only empty values are filled.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0115"
down_revision: str | Sequence[str] | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA = Path(__file__).parent / "data" / "0115_activity_repeat.json"


def load() -> dict[str, dict[str, list[object]]]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def upgrade() -> None:
    op.add_column(
        "plan_template_activities",
        sa.Column("repeat_count", sa.SmallInteger(), nullable=True),
        schema="public",
    )
    op.add_column(
        "plan_template_activities",
        sa.Column("repeat_unit", sa.Text(), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_plan_template_activities_repeat",
        "plan_template_activities",
        # Spelled out with IS NOT NULL: a CHECK that evaluates to NULL passes,
        # so "repeat_unit IN (...)" alone would let half a repeat through.
        "(repeat_count IS NULL AND repeat_unit IS NULL) OR "
        "(repeat_count IS NOT NULL AND repeat_unit IS NOT NULL "
        " AND repeat_count BETWEEN 1 AND 31 "
        " AND repeat_unit IN ('week', 'month', 'season'))",
        schema="public",
    )

    bind = op.get_bind()
    for template_code, activities in load().items():
        template = bind.execute(
            sa.text("SELECT id, status FROM public.plan_templates WHERE code = :c"),
            {"c": template_code},
        ).first()
        if template is None:
            continue
        changed = 0
        for activity_code, (count, unit, _basis) in activities.items():
            res = bind.execute(
                sa.text(
                    "UPDATE public.plan_template_activities "
                    "SET repeat_count = :n, repeat_unit = :u "
                    "WHERE template_id = :t AND code = :c AND repeat_count IS NULL"
                ),
                {"n": count, "u": unit, "t": template.id, "c": activity_code},
            )
            if res.rowcount:
                changed += 1
                # Keep the published snapshot in step, as a publish would.
                bind.execute(
                    sa.text(
                        "UPDATE public.plan_templates "
                        "SET published_snapshot = jsonb_set(published_snapshot, ARRAY[:c], "
                        "    COALESCE(published_snapshot -> :c, '{}'::jsonb) "
                        "    || jsonb_build_object('repeat_count', CAST(:n AS int), "
                        "                          'repeat_unit', CAST(:u AS text))) "
                        "WHERE id = :t AND published_snapshot IS NOT NULL"
                    ),
                    {"c": activity_code, "n": count, "u": unit, "t": template.id},
                )
        if changed and template.status == "published":
            bind.execute(
                sa.text(
                    "UPDATE public.plan_templates "
                    "SET revision = revision + 1, published_at = public.app_now() "
                    "WHERE id = :t"
                ),
                {"t": template.id},
            )


def downgrade() -> None:
    op.drop_constraint(
        "ck_plan_template_activities_repeat",
        "plan_template_activities",
        schema="public",
        type_="check",
    )
    op.drop_column("plan_template_activities", "repeat_unit", schema="public")
    op.drop_column("plan_template_activities", "repeat_count", schema="public")
