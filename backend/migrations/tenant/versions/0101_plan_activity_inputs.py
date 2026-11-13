"""Plan activities carry the input and dose of the template activity (D20).

``input_id`` names a row of ``public.inputs`` (public 0106). There is no
foreign key: tenant schemas do not reference public rows by FK, as with
``farm_scopes.farm_id``. Existing activities are untouched and keep their
free-text ``product_name`` and ``dosage``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0101"
down_revision: str | Sequence[str] | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE plan_activities
            ADD COLUMN input_id uuid,
            ADD COLUMN dose_value numeric,
            ADD COLUMN dose_value_max numeric,
            ADD COLUMN dose_unit text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE plan_activities
            DROP COLUMN IF EXISTS dose_unit,
            DROP COLUMN IF EXISTS dose_value_max,
            DROP COLUMN IF EXISTS dose_value,
            DROP COLUMN IF EXISTS input_id;
        """
    )
