"""Heat units configured per crop (D17): GDD method and start.

The crop catalogue has carried ``gdd_base_temp_c`` / ``gdd_upper_temp_c``
since 0005 (date palm 18 and 38 C, seeded in 0006), but nothing read them:
the platform's only GDD is the fixed base 10/15 series in the tenant's
``weather_derived_daily``. These columns say how a crop counts its heat, so a
tree can read ``{source: heat_units}``, computed per block at evaluation time.

* ``gdd_method``: ``mean`` max(0, (Tmax+Tmin)/2 - base); ``max``
  max(0, Tmax - base); ``min_max_cutoff`` clips Tmin and Tmax to
  [base, upper] (upper when set), then mean - base, floored at 0.
* ``gdd_start_kind`` / ``gdd_start_value``: where the count starts.
  ``date`` with ``MM-DD`` (the latest occurrence on or before today),
  ``planting`` (no value: the block crop's planting date), or ``stage``
  with a stage code (the latest transition into that stage).

All three are nullable on crops, crop_varieties and crop_variety_strains and
inherit crop -> variety -> strain, deepest non-null wins. Kind and value
travel as a pair, so a CHECK keeps them consistent on each row.

Seed: ``date_palm.medjool`` counts by the mean method from the pollination
stage (Organic Medjool Manual 1.7, section 6.5 #3, the FAO method). Its base
of 18 C comes from the date_palm crop row; it is set here only if unset.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0112"
down_revision: str | Sequence[str] | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("crops", "crop_varieties", "crop_variety_strains")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            ALTER TABLE public.{table}
                ADD COLUMN gdd_method text,
                ADD COLUMN gdd_start_kind text,
                ADD COLUMN gdd_start_value text,
                ADD CONSTRAINT ck_{table}_gdd_method
                    CHECK (gdd_method IS NULL
                           OR gdd_method IN ('mean', 'max', 'min_max_cutoff')),
                ADD CONSTRAINT ck_{table}_gdd_start
                    CHECK (
                        (gdd_start_kind IS NULL AND gdd_start_value IS NULL)
                        OR (gdd_start_kind = 'planting' AND gdd_start_value IS NULL)
                        OR (gdd_start_kind = 'date'
                            AND gdd_start_value
                                ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$')
                        OR (gdd_start_kind = 'stage'
                            AND gdd_start_value ~ '^[A-Za-z0-9][A-Za-z0-9_-]{{0,31}}$')
                    );
            """
        )
    # Base 18 C was seeded in 0006; only fill it if someone cleared it.
    op.execute(
        "UPDATE public.crops SET gdd_base_temp_c = 18 "
        "WHERE code = 'date_palm' AND gdd_base_temp_c IS NULL"
    )
    op.execute(
        """
        UPDATE public.crop_varieties
           SET gdd_method = 'mean',
               gdd_start_kind = 'stage',
               gdd_start_value = 'pollination'
         WHERE path = 'date_palm.medjool'
        """
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            ALTER TABLE public.{table}
                DROP CONSTRAINT IF EXISTS ck_{table}_gdd_start,
                DROP CONSTRAINT IF EXISTS ck_{table}_gdd_method,
                DROP COLUMN IF EXISTS gdd_start_value,
                DROP COLUMN IF EXISTS gdd_start_kind,
                DROP COLUMN IF EXISTS gdd_method;
            """
        )
