"""Plan-template activities link to an input with a structured dose (D20).

``product_name`` and ``dosage`` stay as free text for context; a template
activity may now also name an input from the catalogue (public 0106) and a
dose: a value, an optional upper bound for a range, and a unit from the
catalogue's unit list. Existing rows are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0107"
down_revision: str | Sequence[str] | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNITS = (
    "kg/plant",
    "g/plant",
    "L/plant/week",
    "cards/plant",
    "kg/plant/year_of_age",
    "g/100 L",
    "mg/L",
    "%",
    "ppm",
    "traps/ha",
    "kg/ha",
    "L/ha",
    "other",
)


def upgrade() -> None:
    units = ", ".join(f"'{u}'" for u in UNITS)
    op.execute(
        f"""
        ALTER TABLE public.plan_template_activities
            ADD COLUMN input_id uuid REFERENCES public.inputs (id) ON DELETE SET NULL,
            ADD COLUMN dose_value numeric,
            ADD COLUMN dose_value_max numeric,
            ADD COLUMN dose_unit text CHECK (dose_unit IS NULL OR dose_unit IN ({units})),
            ADD CONSTRAINT ck_template_activity_dose CHECK (
                (dose_value IS NULL AND dose_value_max IS NULL) = (dose_unit IS NULL)
                AND (dose_value IS NULL OR dose_value_max IS NULL OR dose_value <= dose_value_max)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.plan_template_activities
            DROP CONSTRAINT IF EXISTS ck_template_activity_dose,
            DROP COLUMN IF EXISTS dose_unit,
            DROP COLUMN IF EXISTS dose_value_max,
            DROP COLUMN IF EXISTS dose_value,
            DROP COLUMN IF EXISTS input_id;
        """
    )
