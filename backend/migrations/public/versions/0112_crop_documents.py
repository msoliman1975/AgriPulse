"""Crop documents (decision D29).

Manuals and other crop documents had no home: nobody could view or download
the Medjool manual from the product. This adds ``public.crop_documents``, a
platform table (no tenant references), one row per uploaded file:

* attached to a crop path -- a crop, a variety or a strain -- and inherited
  downwards, so a document on ``date_palm`` shows for ``date_palm.medjool``
  blocks;
* ``title_en`` and ``title_ar`` both required (D26), ``language``
  (en / ar / other), ``kind`` (manual, guide, standard, report, other) and a
  free-text ``edition`` ("1.7", "v2");
* the file itself lives in the existing uploads bucket under
  ``platform/crop-documents/<id>/<name>``; the row keeps the key, the
  original name, the content type, the size and a SHA-256.

A new edition of a document is a new row with the same ``crop_path`` and
``document_code``; the previous one is kept as history with ``superseded_at``
and ``superseded_by`` set, never deleted. At most one current row exists per
``(crop_path, document_code)``. The ``superseded_by`` foreign key is deferred
so the old row can point at the new one inside the transaction that inserts
it. ``retired_at`` withdraws a document without a successor.

No rows are seeded: the first uploads go through the admin API.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0112"
down_revision: str | Sequence[str] | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.crop_documents (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            document_code text NOT NULL
                CHECK (document_code ~ '^[a-z0-9][a-z0-9_.-]{0,99}$'),
            crop_path text NOT NULL CHECK (length(btrim(crop_path)) > 0),
            title_en text NOT NULL CHECK (length(btrim(title_en)) > 0),
            title_ar text NOT NULL CHECK (length(btrim(title_ar)) > 0),
            language text NOT NULL CHECK (language IN ('en', 'ar', 'other')),
            kind text NOT NULL
                CHECK (kind IN ('manual', 'guide', 'standard', 'report', 'other')),
            edition text NOT NULL CHECK (length(btrim(edition)) > 0),
            s3_key text NOT NULL UNIQUE,
            original_filename text NOT NULL CHECK (length(btrim(original_filename)) > 0),
            content_type text NOT NULL,
            size_bytes bigint NOT NULL CHECK (size_bytes > 0),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            superseded_at timestamptz,
            superseded_by uuid REFERENCES public.crop_documents (id)
                DEFERRABLE INITIALLY DEFERRED,
            retired_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT public.app_now(),
            updated_at timestamptz NOT NULL DEFAULT public.app_now(),
            created_by uuid,
            updated_by uuid,
            CHECK ((superseded_at IS NULL) = (superseded_by IS NULL)),
            CHECK (superseded_by IS NULL OR superseded_by <> id)
        );
        CREATE UNIQUE INDEX uq_crop_documents_current
            ON public.crop_documents (crop_path, document_code)
            WHERE superseded_at IS NULL;
        CREATE INDEX ix_crop_documents_path ON public.crop_documents (crop_path);
        CREATE TRIGGER trg_crop_documents_updated_at BEFORE UPDATE ON public.crop_documents
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.crop_documents;")
