"""Move s2_l2a's ndmi from bands → supported_indices.

0027 appended ``ndmi`` to ``imagery_products.bands``, but ``bands`` is the
list of *raw spectral bands* the compute reads from the scene COG
(``tasks.py`` passes ``product["bands"]`` to ``load_raw_bands_and_aggregate``
as ``band_names``). With a phantom ``ndmi`` band the loader looks for a
raster band that doesn't exist and the pipeline writes zero index COGs.
``ndmi`` belongs in ``supported_indices`` (the product's advertised index
list). This corrective migration moves it, fixing both fresh DBs and any
that already ran 0027.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE public.imagery_products
           SET bands = array_remove(bands, 'ndmi'),
               supported_indices = CASE
                   WHEN NOT ('ndmi' = ANY(supported_indices))
                   THEN array_append(supported_indices, 'ndmi')
                   ELSE supported_indices
               END
         WHERE code = 's2_l2a'
        """
    )


def downgrade() -> None:
    # Restore the 0027 shape (ndmi back on bands) so the chain is symmetric.
    op.execute(
        """
        UPDATE public.imagery_products
           SET supported_indices = array_remove(supported_indices, 'ndmi'),
               bands = CASE
                   WHEN NOT ('ndmi' = ANY(bands))
                   THEN array_append(bands, 'ndmi')
                   ELSE bands
               END
         WHERE code = 's2_l2a'
        """
    )
