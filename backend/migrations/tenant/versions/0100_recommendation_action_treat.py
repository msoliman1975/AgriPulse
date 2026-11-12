"""Add ``treat`` to the recommendation action types.

The Medjool v2 decision trees use a *treat* action on 16 rules (decision D4):
treating and soil-covering offshoot and pruning cuts, Bt for lesser date
moth, sulphur for dust mite, removing and burning rotted spathes, black scorch
heart treatment and white scale. About half of these are not a spray, so they
cannot honestly be written as ``spray``. Both trees documents use "Treat"
(AR «معالجة»).

Widens ``ck_recommendations_action_type`` (tenant 0015). No row is touched.
Downgrade narrows back to the 0015 set; it is safe only while no row uses
``treat``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0100"
down_revision: str | Sequence[str] | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "action_type IN ('irrigate','fertilize','spray','scout',"
    "'harvest_window','prune','no_action','other')"
)
_NEW = (
    "action_type IN ('irrigate','fertilize','spray','scout',"
    "'harvest_window','prune','treat','no_action','other')"
)


def upgrade() -> None:
    op.drop_constraint("ck_recommendations_action_type", "recommendations", type_="check")
    op.create_check_constraint("ck_recommendations_action_type", "recommendations", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_recommendations_action_type", "recommendations", type_="check")
    op.create_check_constraint("ck_recommendations_action_type", "recommendations", _OLD)
