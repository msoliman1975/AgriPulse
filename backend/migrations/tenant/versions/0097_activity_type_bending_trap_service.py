"""Add ``bending`` and ``trap_service`` to the plan activity types.

The organic Medjool templates (public 0099) need two operations the
vocabulary did not have: bunch bending (manual 9.3) and pheromone trap
servicing for red palm weevil (manual 10.1, every 7-14 days all year).

Widens ``ck_plan_activities_activity_type`` the way 0048 did. No row is
touched. Downgrade narrows back to the 0048 set; it is safe only while no
row uses the two new types.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0097"
down_revision: str | Sequence[str] | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "activity_type IN ('planting','fertilizing','spraying','pruning',"
    "'harvesting','irrigation','soil_prep','observation',"
    "'pollination','growth_regulator','thinning','bagging','hilling')"
)
_NEW = (
    "activity_type IN ('planting','fertilizing','spraying','pruning',"
    "'harvesting','irrigation','soil_prep','observation',"
    "'pollination','growth_regulator','thinning','bagging','hilling',"
    "'bending','trap_service')"
)


def upgrade() -> None:
    op.drop_constraint("ck_plan_activities_activity_type", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_activity_type", "plan_activities", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_plan_activities_activity_type", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_activity_type", "plan_activities", _OLD)
