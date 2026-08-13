"""Seed the BSI and MSI indices into the imagery catalog.

Both come from the indices-guide gap audit (docs/guide/agri-indices-gap-analysis.html):
they were the only two spectral indices in the guide that our existing Sentinel-2
band set can already produce, so neither needs a provider or evalscript change.

  * ``bsi`` — Bare Soil Index, from SWIR1/red vs NIR/blue. The only index we
    carry that measures the *ground* rather than the canopy, so it reads
    planting gaps and plant loss that NDVI can only render as "less green".
  * ``msi`` — Moisture Stress Index, SWIR1/NIR. Same physical signal as the
    existing ``ndmi`` on an unbounded, inverted scale.

⚠️ ``msi`` is the first index in the catalog that is **not** a normalized
difference: its range is a ratio in roughly [0, 3], and it runs the opposite
way to every other row (higher = more stress). The ``value_min``/``value_max``
below are the chart-axis bounds the SPA reads, so they must reflect that or
every MSI chart renders as a flat line pinned to the top of a [-1, 1] axis.

Both rows go in ``supported_indices``, NOT ``bands``. Migration 0027 put
``ndmi`` in ``bands`` by mistake and needed 0029 to correct it: ``bands`` is
the raw spectral band list the COG reader consumes, while ``supported_indices``
is the advertised index list. Writing a computed index into ``bands`` makes the
loader look for a band that no scene contains.

Revision ID: 0061
Revises: 0056
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CODES: tuple[str, ...] = ("bsi", "msi")

# Parameterised rather than f-string/$tag$ interpolated: the Arabic names carry
# RTL text that is easy to mangle through string building, and binds keep the
# migration honest if a name ever gains a quote.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "bsi",
        "name_en": "Bare Soil Index",
        "name_ar": "مؤشر التربة العارية",
        "formula_text": "((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Proportion of exposed soil between plants. Positive values mean soil "
            "reflectance dominates the pixel; negative means canopy does. Reads "
            "planting gaps, plant loss and poor establishment — the inverse of "
            "ground cover, which no other index here measures directly."
        ),
    },
    {
        "code": "msi",
        "name_en": "Moisture Stress Index",
        "name_ar": "مؤشر الإجهاد الرطوبي",
        "formula_text": "SWIR1 / NIR",
        # Not [-1, 1]: this is a ratio. Real surface reflectance keeps it under
        # ~3; the bounds drive chart axes, not a physical clamp.
        "value_min": 0.0,
        "value_max": 3.0,
        "physical_meaning": (
            "Canopy water stress, and the one index here that runs backwards: "
            "HIGHER means MORE stress. Below ~0.4 is well-watered, above ~1.0 is "
            "high stress. Carries the same signal as NDMI on an inverted, "
            "unbounded scale — the two are a monotone transform of each other, "
            "ndmi = (1 - msi) / (1 + msi)."
        ),
    },
)


def upgrade() -> None:
    insert = sa.text(
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
    bind = op.get_bind()
    for entry in _INDICES:
        bind.execute(insert, entry)

    # Keep the s2_l2a product's advertised index list in sync. `supported_indices`
    # — not `bands`; see the module docstring.
    #
    # The array bind is TYPED rather than postfix-cast. `:codes::text[]` reads
    # naturally but dies inside `text()` — the driver sees the `::` and the
    # statement fails with `syntax error at or near ":"`. A declared
    # `bindparam(..., type_=ARRAY(Text))` taking a real Python list is the form
    # that survives, and it means the value never round-trips through a
    # hand-built `{a,b}` literal either.
    codes_param = sa.bindparam("codes", type_=postgresql.ARRAY(sa.Text()))
    bind.execute(
        sa.text(
            """
            UPDATE public.imagery_products
               SET supported_indices = supported_indices || :codes
             WHERE code = 's2_l2a'
               AND provider_id = (
                   SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub'
               )
               AND NOT (supported_indices @> :codes)
            """
        ).bindparams(codes_param),
        {"codes": list(_CODES)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    for code in _CODES:
        bind.execute(
            sa.text(
                """
                UPDATE public.imagery_products
                   SET supported_indices = array_remove(supported_indices, :code)
                 WHERE code = 's2_l2a'
                   AND provider_id = (
                       SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub'
                   )
                """
            ),
            {"code": code},
        )
    bind.execute(
        sa.text("DELETE FROM public.indices_catalog WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", type_=postgresql.ARRAY(sa.Text()))
        ),
        {"codes": list(_CODES)},
    )
