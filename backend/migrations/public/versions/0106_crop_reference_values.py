"""Crop reference values (decisions D18 and D23).

Salt tolerance, yield, fruit weight, bunch load and spacing had no home: the
catalogue's `default_thresholds` is untyped and nothing reads it. This adds
`public.crop_reference_values`: one row per (crop path, key), with a value
and/or a min-max range and a note. A path inherits every key it does not set
from the shallower paths, the same rule the Health tab follows. The keys and
their units are defined in code (`app.modules.reference_values.keys`), so a
row cannot carry a key nobody reads or a unit nobody expects.

Seeded only with what the Medjool manual 1.7 states, each linked to the
source and confidence the manual gives (D27):

* date_palm, from 4.1 #6 (FAO [47], High): no yield loss up to soil ECe
  4.0 dS/m, then 3.6% per further dS/m.
* date_palm, from 4.1 #5 (FAO [44], Medium): irrigation water up to
  3.5 dS/m with a 7% leaching requirement.
* date_palm, from 7.2 #5 (FAO model [6], Medium): 10 m between rows,
  8 m in the row.
* date_palm.medjool, from 3.1 #7 and #5 (FAO [5], High): 60-72 kg per adult
  palm carrying 10-12 bunches; fruit 20 g, 18-28 g.
* date_palm.medjool, from 7.2 #5 ([35], Medium): the Egyptian Medjool study
  in El-Minia used 9 x 9 m. Gap 6 of the manual: no Western Desert spacing.

Plants per hectare is not stored: it follows from the two spacings.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106"
down_revision: str | Sequence[str] | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MANUAL = "medjool_manual_1_7"

# (crop_path, key, value, min, max, note, [(manual ref, confidence)])
SEED: tuple[tuple, ...] = (
    (
        "date_palm",
        "soil_ece_threshold_ds_m",
        4.0,
        None,
        None,
        "Manual 1.7, 4.1 #6: fruit yield is not reduced up to soil ECe 4.0 dS/m.",
        [(47, "high")],
    ),
    (
        "date_palm",
        "yield_loss_pct_per_ds_m",
        3.6,
        None,
        None,
        "Manual 1.7, 4.1 #6: above the threshold, yield falls 3.6% per further 1 dS/m "
        "(about 25% loss at 10.9 dS/m, 50% at 17.9 dS/m).",
        [(47, "high")],
    ),
    (
        "date_palm",
        "irrigation_water_ecw_max_ds_m",
        3.5,
        None,
        None,
        "Manual 1.7, 4.1 #5: irrigation water up to 3.5 dS/m does not reduce yield if a 7% "
        "leaching requirement is met; at 5.3 dS/m (11% leaching) yield falls about 10%, and "
        "at 10 dS/m (21% leaching) about 50%.",
        [(44, "medium")],
    ),
    (
        "date_palm",
        "leaching_requirement_pct",
        7,
        None,
        None,
        "Manual 1.7, 4.1 #5: the leaching requirement at irrigation water of 3.5 dS/m.",
        [(44, "medium")],
    ),
    (
        "date_palm",
        "row_spacing_m",
        10,
        None,
        None,
        "Manual 1.7, 7.2 #5: FAO's model plantation, 10 m between rows (125 palms/ha with 8 m in "
        "the row).",
        [(6, "medium")],
    ),
    (
        "date_palm",
        "in_row_spacing_m",
        8,
        None,
        None,
        "Manual 1.7, 7.2 #5: FAO's model plantation, 8 m between palms in the row.",
        [(6, "medium")],
    ),
    (
        "date_palm.medjool",
        "yield_per_plant_kg",
        None,
        60,
        72,
        "Manual 1.7, 3.1 #7: an adult Medjool palm carrying 10 to 12 bunches yields about "
        "60 to 72 kg of high-quality dates.",
        [(5, "high")],
    ),
    (
        "date_palm.medjool",
        "bunches_per_plant",
        None,
        10,
        12,
        "Manual 1.7, 3.1 #7: an adult palm carrying 10 to 12 bunches.",
        [(5, "high")],
    ),
    (
        "date_palm.medjool",
        "fruit_weight_g",
        20,
        18,
        28,
        "Manual 1.7, 3.1 #5: average fruit weight of 20 g (18-28 g) under Israeli conditions, "
        "thinned to about 30 strands of 10 fruits.",
        [(5, "high"), (6, "high")],
    ),
    (
        "date_palm.medjool",
        "row_spacing_m",
        9,
        None,
        None,
        "Manual 1.7, 7.2 #5: the Egyptian Medjool study in El-Minia used 9 x 9 m. Gap 6: no "
        "Medjool spacing for Western Desert orchards was found.",
        [(35, "medium")],
    ),
    (
        "date_palm.medjool",
        "in_row_spacing_m",
        9,
        None,
        None,
        "Manual 1.7, 7.2 #5: the Egyptian Medjool study in El-Minia used 9 x 9 m.",
        [(35, "medium")],
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.crop_reference_values (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            crop_path text NOT NULL CHECK (crop_path ~ '^[a-z0-9_]+(\\.[a-z0-9_]+)*$'),
            key text NOT NULL CHECK (key ~ '^[a-z0-9_]+$'),
            value numeric,
            value_min numeric,
            value_max numeric,
            note text,
            created_at timestamptz NOT NULL DEFAULT public.app_now(),
            updated_at timestamptz NOT NULL DEFAULT public.app_now(),
            updated_by uuid,
            UNIQUE (crop_path, key),
            CHECK (value IS NOT NULL OR value_min IS NOT NULL OR value_max IS NOT NULL),
            CHECK (value_min IS NULL OR value_max IS NULL OR value_min <= value_max)
        );
        CREATE TRIGGER trg_crop_reference_values_updated_at
            BEFORE UPDATE ON public.crop_reference_values
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
        """
    )
    conn = op.get_bind()
    for crop_path, key, value, vmin, vmax, note, refs in SEED:
        conn.execute(
            sa.text(
                "INSERT INTO public.crop_reference_values "
                "(crop_path, key, value, value_min, value_max, note) "
                "VALUES (:p, :k, :v, :lo, :hi, :note)"
            ),
            {"p": crop_path, "k": key, "v": value, "lo": vmin, "hi": vmax, "note": note},
        )
        for ref_number, confidence in refs:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO public.source_links
                        (source_id, entity_type, entity_key, detail, confidence)
                    SELECT a.source_id, 'reference_value', :ek, '', :conf
                      FROM public.source_aliases a
                     WHERE a.document_code = :doc AND a.ref_number = :num
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"ek": f"{crop_path}#{key}", "conf": confidence, "doc": MANUAL, "num": ref_number},
            )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.source_links WHERE entity_type = 'reference_value'; "
        "DROP TABLE IF EXISTS public.crop_reference_values;"
    )
