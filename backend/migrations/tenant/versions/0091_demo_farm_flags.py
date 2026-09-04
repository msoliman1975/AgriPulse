"""Mark a farm as the demo farm, and record when it was frozen.

A tenant created by a platform admin can be given a demo farm, and a
self-serve trial gets one by default. It sits in the tenant's own schema
next to whatever farms the customer draws, so the flag belongs on the
farm row, not on the tenant.

Two columns.

`is_demo` says this farm is the seeded demo, not the customer's own land.
It has three jobs: keep the farm out of the meter, the plan caps and
billing; let the interface label it; and let the freeze find it.

`demo_frozen_at` records the moment the demo farm was made read-only.
NULL means it is live and the customer can edit it, which is the state
during a trial. A timestamp means the trial ended or the tenant moved to
a paid plan, so the farm stops accepting writes and stops consuming
compute: no daily imagery import, no decision tree runs, no index
recomputation. A timestamp rather than a second boolean, because the
question "when did this stop costing us money" gets asked.

Neither column changes anything for an existing farm. Every row gets
`is_demo = false` and `demo_frozen_at = NULL`, which is exactly today's
behaviour.

The partial index exists because every reader asks the same question:
"which farm in this tenant is the demo one". There is at most one, and
the index is small because almost every row is excluded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "farms",
        sa.Column("demo_frozen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_farms_is_demo",
        "farms",
        ["id"],
        unique=False,
        postgresql_where=sa.text("is_demo"),
    )
    # A frozen farm that is not a demo farm has no meaning: the freeze is
    # the end of a demo, and a customer's own farm is never frozen this
    # way. The check keeps the two columns from drifting apart.
    #
    # The name passed here is the `%(constraint_name)s` half of the
    # `ck_%(table_name)s_%(constraint_name)s` convention on Base.metadata.
    # Passing the full name produces `ck_farms_ck_farms_...`, which is how
    # every other check constraint on this table ended up doubled.
    op.create_check_constraint(
        "demo_frozen_only_when_demo",
        "farms",
        "demo_frozen_at IS NULL OR is_demo",
    )


def downgrade() -> None:
    op.drop_constraint("ck_farms_demo_frozen_only_when_demo", "farms", type_="check")
    op.drop_index("ix_farms_is_demo", table_name="farms")
    op.drop_column("farms", "demo_frozen_at")
    op.drop_column("farms", "is_demo")
