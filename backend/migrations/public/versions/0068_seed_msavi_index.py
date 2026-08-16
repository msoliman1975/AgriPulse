"""Seed the MSAVI index into the imagery catalog.

MSAVI2 (Qi et al. 1994) is ``savi`` with its soil factor solved per pixel
rather than pinned at L = 0.5. It needs only RED and NIR — both already in
the s2_l2a band set — so like ``bsi``/``msi`` in 0061 this is a catalog row
and a formula, with no provider or evalscript change behind it.

Why it earns a row of its own next to ``savi``: L = 0.5 is only correct at
moderate cover. Sparse canopy wants L nearer 1 and full canopy nearer 0, so
one constant under-corrects at one end of the season and over-corrects at
the other. MSAVI2 folds the closed-form solution for L back into the
formula, which matters most for exactly our case — widely spaced trees over
bright sand, where the soil fraction of a pixel is both large and moving.

``unit`` is left to its ``''`` default (0067): this is a dimensionless
normalized index like every spectral row but ``lst``.

⚠️ ``formula_text`` uses ``√`` rather than the word ``sqrt`` on purpose.
``observer/pixels.py`` renders a catalog formula by substituting band names
for numbers, and ``test_every_catalog_formula_is_fully_substitutable``
fails on any surviving run of Latin letters — a spelled-out ``sqrt`` would
read as an unmapped band token and break that guard.

Both the row and the ``supported_indices`` append are idempotent. New scenes
compute MSAVI going forward; backfilling historical aggregates is a separate
operation (Backfill Console → Compute indices) and out of scope here.

Revision ID: 0068
Revises: 0067
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068"
down_revision: str | Sequence[str] | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CODES: tuple[str, ...] = ("msavi",)

# Parameterised rather than interpolated: the Arabic name carries RTL text
# that is easy to mangle through string building, and the formula carries
# non-ASCII maths symbols.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "msavi",
        "name_en": "Modified Soil-Adjusted Vegetation Index",
        "name_ar": "مؤشر الغطاء النباتي المعدّل لأثر التربة",
        "formula_text": "(2 * NIR + 1 - √((2 * NIR + 1)^2 - 8 * (NIR - Red))) / 2",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Canopy vigour with the soil background corrected out, and unlike "
            "SAVI the correction adapts to how much canopy is actually there "
            "instead of assuming moderate cover. The more trustworthy vigour "
            "reading while soil still shows between plants — early season, "
            "wide tree spacing, or a thin stand. Reads close to SAVI and "
            "below NDVI wherever bare ground is in the pixel."
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

    # `supported_indices`, NOT `bands` — see 0061's docstring and the 0027/0029
    # pair that established the distinction: `bands` is the raw spectral list
    # the COG reader consumes, so a computed index written there makes the
    # loader hunt for a band no scene contains.
    #
    # The array bind is TYPED rather than postfix-cast: `:codes::text[]` reads
    # naturally but dies inside `text()` with `syntax error at or near ":"`.
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
