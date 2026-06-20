"""Extend plan_activities.activity_type CHECK with the scientific-plan vocabulary.

Adds pollination, growth_regulator, thinning, bagging, hilling to the
``ck_plan_activities_activity_type`` constraint created in 0010 so that
template-applied activities using the extended vocabulary (date-palm
pollination, mango PBZ growth-regulator, fruit/strand thinning, bunch
bagging, potato hilling) can be materialised into plan_activities.

Data-safe: only widens the allowed set; no row touched. Downgrade narrows
back to the original 8 (safe only if no rows use the new types — see note).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "activity_type IN ('planting','fertilizing','spraying','pruning',"
    "'harvesting','irrigation','soil_prep','observation')"
)
_NEW = (
    "activity_type IN ('planting','fertilizing','spraying','pruning',"
    "'harvesting','irrigation','soil_prep','observation',"
    "'pollination','growth_regulator','thinning','bagging','hilling')"
)


def upgrade() -> None:
    op.drop_constraint("ck_plan_activities_activity_type", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_activity_type", "plan_activities", _NEW)


def downgrade() -> None:
    # Narrow back to the original 8. Rows using the new types would violate
    # this; the migration-roundtrip CI runs on an empty table so it is safe
    # there. In a populated DB, remap/delete extended-type rows first.
    op.drop_constraint("ck_plan_activities_activity_type", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_activity_type", "plan_activities", _OLD)
