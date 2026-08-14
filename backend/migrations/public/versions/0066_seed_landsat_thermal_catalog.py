"""Seed the Landsat C2 L2 thermal provider, product and the LST/CWSI/SMI indices.

Closes the thermal gap in docs/guide/agri-indices-gap-analysis.html
section 04. Those three indices were the only ones in the guide our
Sentinel-2 band set cannot produce at all: none of the 13 MSI bands
measures emitted thermal infrared, so this needed a second source
rather than a second formula.

The source is Landsat 8/9 Collection-2 **Level-2** surface temperature
via Microsoft Planetary Computer. Note this contradicts the gap
analysis's own recommendation, which assumed we could reach Landsat
Level-2 through Sentinel Hub: our CDSE free-tier account serves
`landsat-ot-l1`, which is Level-1 TOA radiance, and deriving surface
temperature from that means writing the atmospheric-correction and
emissivity-retrieval chain ourselves. See the adapter's module
docstring for the full comparison.

Three things about these rows differ from every catalog row before them:

  * ``cost_tier`` is ``'free'`` for the first time. PC serves the STAC
    search anonymously and issues blob SAS tokens without an account.
  * ``resolution_m`` is 30, and the thermal band is coarser still —
    100 m native, resampled by USGS onto the 30 m grid. Block-level
    numbers must be presented accordingly; our average block is 3.10 ha
    (~158 m a side) and our smallest is 0.53 ha, a fraction of a single
    thermal pixel.
  * ``lst`` is the first index in the catalog carrying a **unit**.
    Every existing index is a dimensionless ratio; LST is degrees
    Celsius, so its ``value_min``/``value_max`` are an actual
    temperature range rather than the [-1, 1] most rows use. ``msi``
    (0065-era, range [0, 3]) set the precedent that these bounds are
    chart-axis hints, not a physical clamp.

``bands`` deliberately excludes ``qa_pixel``. It is a quality band, not
a science band, and rides as a trailing band exactly the way SCL does
for Sentinel-2 — migration 0027 put ``ndmi`` in ``bands`` by mistake and
needed 0029 to correct it, so the distinction is load-bearing.

No subscription rows are created. Both `imagery_farm_subscriptions` and
`imagery_aoi_subscriptions` are unique on (farm_id, product_id) /
(block_id, product_id), so a thermal subscription coexists with the
Sentinel-2 one rather than replacing it — but nothing fetches until
somebody opts a farm in, which is deliberate and mirrors how
`fetch_farm_aoi` defaults FALSE.

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-14
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PROVIDER_CODE = "landsat_pc"
_PRODUCT_CODE = "landsat_c2_l2_st"
_INDEX_CODES: tuple[str, ...] = ("lst", "cwsi", "smi")

# Documents what an `imagery_providers.config` blob may carry. Not
# validated here (FastAPI does that at the API edge); it exists so a
# platform admin editing the catalog has machine-readable guidance.
# There are no credential fields on purpose — PC is anonymous.
_PROVIDER_CONFIG_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["stac_url", "sas_url"],
    "properties": {
        "stac_url": {"type": "string", "format": "uri"},
        "sas_url": {"type": "string", "format": "uri"},
    },
    "additionalProperties": False,
}

# Parameterised rather than interpolated: the Arabic names carry RTL
# text that string building mangles easily, and binds keep the migration
# honest if a name ever gains a quote. Same reasoning as 0061.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "lst",
        "name_en": "Land Surface Temperature",
        "name_ar": "درجة حرارة سطح الأرض",
        # Written against the band name, not the raw DN expression, so the
        # observer's per-pixel explain can substitute it: the adapter has
        # already applied Collection-2's `DN * 0.00341802 + 149.0`, so the
        # band arrives in kelvin and only the unit conversion is left.
        "formula_text": "LWIR11 - 273.15",
        # Degrees Celsius, NOT a ratio. Bounds span an Egyptian year:
        # irrigated canopy sits near 25-35 degC at the ~10:20 local
        # overpass, bare desert soil exceeds 55 degC in summer.
        "value_min": 0.0,
        "value_max": 60.0,
        "physical_meaning": (
            "Radiometric temperature of the ground surface in degrees Celsius, "
            "measured at roughly 10:20 local time. A canopy transpiring freely "
            "cools itself below air temperature; a water-stressed one closes its "
            "stomata and heats up. This is the only index here in physical units "
            "rather than a ratio. Native resolution is 100 m, resampled to the "
            "30 m grid, so it is a farm-scale signal: our average block is about "
            "158 m a side and the smallest is a fraction of one thermal pixel."
        ),
    },
    {
        "code": "cwsi",
        "name_en": "Crop Water Stress Index",
        "name_ar": "مؤشر إجهاد المحصول المائي",
        "formula_text": "(LST - Tair) / (dT_dry - dT_wet)",
        "value_min": 0.0,
        "value_max": 1.0,
        "physical_meaning": (
            "How close the canopy is to shutting down transpiration, on a 0-1 "
            "scale: 0 is a freely transpiring, well-watered canopy and 1 is a "
            "fully stressed one. Derived from the gap between surface and air "
            "temperature, with air temperature interpolated to the satellite "
            "overpass minute from the hourly weather feed. Ships in its "
            "simplified temperature-difference form; a rigorous CWSI needs a "
            "crop- and site-specific non-water-stressed baseline, and the "
            "Egyptian-mango calibration is not done yet, so read it as a "
            "relative signal over time rather than an absolute threshold."
        ),
    },
    {
        "code": "smi",
        "name_en": "Soil Moisture Index",
        "name_ar": "مؤشر رطوبة التربة",
        "formula_text": "(LST_max - LST) / (LST_max - LST_min) at equal NDVI",
        "value_min": 0.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Relative surface wetness from the LST-NDVI triangle: 0 sits on the "
            "dry edge, 1 on the wet edge. For a given amount of greenness, wetter "
            "ground runs cooler, so the spread of temperature at equal NDVI maps "
            "to moisture. The NDVI it uses comes from the Landsat scene itself, "
            "not our 10 m Sentinel-2 stack — the triangle is only valid when both "
            "surfaces are the same ground at the same moment."
        ),
    },
)


def upgrade() -> None:
    bind = op.get_bind()

    # Every catalog table has a UNIQUE on `code` (providers, indices) or
    # (provider_id, code) (products), so re-running upgrade is a no-op.
    bind.execute(
        sa.text(
            """
            INSERT INTO public.imagery_providers (code, name, kind, config_schema)
            VALUES (:code, :name, :kind, CAST(:config_schema AS jsonb))
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "code": _PROVIDER_CODE,
            "name": "Landsat C2 L2 (Planetary Computer)",
            # Open data we retrieve and process ourselves, as opposed to
            # Sentinel Hub's `commercial_api` where the provider does the
            # processing and bills for it.
            "kind": "open_self_managed",
            "config_schema": json.dumps(_PROVIDER_CONFIG_SCHEMA),
        },
    )

    # Array binds are TYPED rather than postfix-cast: `:bands::text[]`
    # reads naturally but dies inside `text()` — the driver sees the `::`
    # and the statement fails with `syntax error at or near ":"`. 0061
    # hit this and documented it.
    bind.execute(
        sa.text(
            """
            INSERT INTO public.imagery_products (
                provider_id, code, name, resolution_m, revisit_days_avg,
                bands, supported_indices, cost_tier
            )
            SELECT
                (SELECT id FROM public.imagery_providers WHERE code = :provider_code),
                :code, :name, :resolution_m, :revisit_days_avg,
                :bands, :supported_indices, :cost_tier
            ON CONFLICT (provider_id, code) DO NOTHING
            """
        ).bindparams(
            sa.bindparam("bands", type_=postgresql.ARRAY(sa.Text())),
            sa.bindparam("supported_indices", type_=postgresql.ARRAY(sa.Text())),
        ),
        {
            "provider_code": _PROVIDER_CODE,
            "code": _PRODUCT_CODE,
            "name": "Landsat 8/9 Collection-2 Level-2 Surface Temperature",
            # The delivery grid. The thermal band is 100 m native,
            # resampled here by USGS; `lst`'s physical_meaning says so,
            # because this number alone would overstate the detail.
            "resolution_m": 30.00,
            # Nominal for the Landsat 8 + 9 constellation. Measured over
            # the Bashier Elkhier bbox the mean gap is shorter (~4 d)
            # thanks to sidelap between adjacent paths, but that is
            # path-dependent and the nominal is the safe value for
            # staleness thresholds.
            "revisit_days_avg": 8.00,
            # Science bands only. `qa_pixel` is a quality band and rides
            # as a trailing band, the way SCL does for Sentinel-2.
            "bands": ["lwir11", "red", "nir08"],
            "supported_indices": list(_INDEX_CODES),
            # First `free` row in the catalog: PC's STAC search is
            # anonymous and its SAS tokens need no account.
            "cost_tier": "free",
        },
    )

    insert_index = sa.text(
        """
        INSERT INTO public.indices_catalog (
            code, name_en, name_ar, formula_text,
            value_min, value_max, physical_meaning, is_standard
        )
        VALUES (
            :code, :name_en, :name_ar, :formula_text,
            :value_min, :value_max, :physical_meaning, TRUE
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    for entry in _INDICES:
        bind.execute(insert_index, entry)


def downgrade() -> None:
    bind = op.get_bind()
    codes_param = sa.bindparam("codes", type_=postgresql.ARRAY(sa.Text()))

    bind.execute(
        sa.text("DELETE FROM public.indices_catalog WHERE code = ANY(:codes)").bindparams(
            codes_param
        ),
        {"codes": list(_INDEX_CODES)},
    )
    # Product before provider — the product carries the FK.
    bind.execute(
        sa.text(
            """
            DELETE FROM public.imagery_products
             WHERE code = :code
               AND provider_id = (
                   SELECT id FROM public.imagery_providers WHERE code = :provider_code
               )
            """
        ),
        {"code": _PRODUCT_CODE, "provider_code": _PROVIDER_CODE},
    )
    bind.execute(
        sa.text("DELETE FROM public.imagery_providers WHERE code = :code"),
        {"code": _PROVIDER_CODE},
    )
