"""Inputs catalogue (decision D20).

Manures, biologicals, sprays, traps and bags lived only as free text in
plan-template notes (`product_name`, `dosage`, English only), so nothing could
be checked, filtered or translated, and nothing said whether an input is
allowed on an organic farm. This adds:

* ``public.inputs`` -- one row per input. ``tenant_id`` NULL is the platform
  catalogue; a tenant may add its own rows, which only it sees. Name EN/AR,
  category, active ingredient or organism, application methods, organic
  status (permitted, restricted, not permitted or unverified) with the list
  it was checked against, optional PHI and REI, crop scope.
* ``public.input_doses`` -- the doses a source recommends, each a value
  and/or a range with a unit, the context ("in the basin, end of October"),
  and the crop path it applies to.

Medjool seed (`data/0106_medjool_inputs.json`): only inputs and doses the
manual 1.7 names, each dose with the manual row it comes from and linked to
that row's sources and confidence (D27). Rows from the manual's annexes
cite the annex's own source list, so their links resolve against it. Every Medjool input is marked
``unverified``: the manual says the list of inputs permitted under Egyptian
Law 12/2020 was not retrieved (section 13, gap 5) and every input must be
checked with the certifier.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0106"
down_revision: str | Sequence[str] | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).parent / "data" / "0106_medjool_inputs.json"

CATEGORIES = (
    "organic_fertiliser",
    "biological_agent",
    "mineral_or_botanical_treatment",
    "foliar_nutrient",
    "growth_regulator",
    "trap_or_bait",
    "bag_or_cover",
)
METHODS = ("basin", "spray", "dust", "release", "trap", "injection", "cover", "foliar", "soil_mix")
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


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE public.inputs (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            tenant_id uuid REFERENCES public.tenants (id) ON DELETE CASCADE,
            code text NOT NULL CHECK (code ~ '^[a-z0-9_]+$'),
            name_en text NOT NULL CHECK (length(btrim(name_en)) > 0),
            name_ar text,
            category text NOT NULL CHECK (category IN ({_in(CATEGORIES)})),
            active_ingredient text,
            methods text[] NOT NULL DEFAULT '{{}}'
                CHECK (methods <@ ARRAY[{_in(METHODS)}]::text[]),
            organic_status text NOT NULL DEFAULT 'unverified'
                CHECK (organic_status IN ('permitted', 'restricted', 'not_permitted',
                                          'unverified')),
            organic_list text,
            phi_days integer CHECK (phi_days IS NULL OR phi_days >= 0),
            rei_hours integer CHECK (rei_hours IS NULL OR rei_hours >= 0),
            crop_paths text[] NOT NULL DEFAULT '{{}}',
            notes text,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid,
            updated_by uuid
        );
        CREATE UNIQUE INDEX uq_inputs_platform_code ON public.inputs (code)
            WHERE tenant_id IS NULL;
        CREATE UNIQUE INDEX uq_inputs_tenant_code ON public.inputs (tenant_id, code)
            WHERE tenant_id IS NOT NULL;
        CREATE INDEX ix_inputs_crop_paths ON public.inputs USING gin (crop_paths);
        CREATE TRIGGER trg_inputs_updated_at BEFORE UPDATE ON public.inputs
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

        CREATE TABLE public.input_doses (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            input_id uuid NOT NULL REFERENCES public.inputs (id) ON DELETE CASCADE,
            crop_path text,
            value numeric,
            value_min numeric,
            value_max numeric,
            unit text NOT NULL CHECK (unit IN ({_in(UNITS)})),
            unit_note text,
            context text,
            reference text,
            sort_order integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (value IS NOT NULL OR value_min IS NOT NULL OR value_max IS NOT NULL),
            CHECK (value_min IS NULL OR value_max IS NULL OR value_min <= value_max),
            CHECK (unit <> 'other' OR unit_note IS NOT NULL)
        );
        CREATE INDEX ix_input_doses_input ON public.input_doses (input_id, sort_order);
        """
    )
    if not _DATA.exists():
        return
    data = json.loads(_DATA.read_text(encoding="utf-8"))
    conn = op.get_bind()
    for item in data["inputs"]:
        input_id = conn.execute(
            sa.text(
                """
                INSERT INTO public.inputs
                    (code, name_en, name_ar, category, active_ingredient, methods,
                     organic_status, organic_list, crop_paths, notes)
                VALUES (:code, :name_en, :name_ar, :category, :ai, :methods,
                        'unverified', :organic_list, :crop_paths, :notes)
                RETURNING id
                """
            ),
            {
                "code": item["code"],
                "name_en": item["name_en"],
                "name_ar": item.get("name_ar"),
                "category": item["category"],
                "ai": item.get("active_ingredient"),
                "methods": item.get("methods") or [],
                "organic_list": data["organic_list"],
                "crop_paths": item.get("crop_paths") or [],
                "notes": item.get("notes"),
            },
        ).scalar_one()
        for order, dose in enumerate(item.get("doses") or []):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO public.input_doses
                        (input_id, crop_path, value, value_min, value_max, unit, unit_note,
                         context, reference, sort_order)
                    VALUES (:iid, :path, :v, :lo, :hi, :unit, :unit_note, :context, :ref, :o)
                    """
                ),
                {
                    "iid": input_id,
                    "path": dose.get("crop_path"),
                    "v": dose.get("value"),
                    "lo": dose.get("value_min"),
                    "hi": dose.get("value_max"),
                    "unit": dose["unit"],
                    "unit_note": dose.get("unit_note"),
                    "context": dose.get("context"),
                    "ref": f"Manual 1.7, {dose['section']}",
                    "o": order,
                },
            )
        for link in item.get("links") or []:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO public.source_links
                        (source_id, entity_type, entity_key, detail, confidence)
                    SELECT a.source_id, 'input', :code, :detail, :conf
                      FROM public.source_aliases a
                     WHERE a.document_code = :doc AND a.ref_number = :num
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "code": item["code"],
                    "detail": link["section"],
                    "conf": link["confidence"],
                    "doc": link["doc"],
                    "num": link["ref"],
                },
            )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.source_links WHERE entity_type = 'input'; "
        "DROP TABLE IF EXISTS public.input_doses; "
        "DROP TABLE IF EXISTS public.inputs;"
    )
