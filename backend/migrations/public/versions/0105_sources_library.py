"""Sources library (decision D27).

Template notes and tree provenance cite "[n]" numbers, but no reference list
was stored, so the numbers led nowhere. This adds a platform library:

* ``public.sources`` -- one row per publication or page: a citation as the
  documents give it, plus kind, year, DOI and URL where known.
* ``public.source_aliases`` -- each document's own numbering, so "[7] in the
  trees document" still resolves after deduplication.
* ``public.source_links`` -- what cites a source (a finding, a tree, a tree
  parameter, a signal, a plan-template activity, a reference value, an
  input, a crop attribute), each link with its own confidence: high, medium,
  low or expert_inference.

Seeded from the four reference lists of the Medjool documents (manual 1.7
section 14: 82; Annex A: 32; Annex B: 60; trees document v2: 45), 219 entries
deduplicated by DOI, else by URL, into 152 sources. The trees document's
"Expert inference from the sources above" entry is not a publication; it is
the expert_inference confidence level instead. Citations are kept exactly as
the documents write them; nothing is invented.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0105"
down_revision: str | Sequence[str] | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).parent / "data" / "0105_sources_library.json"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.sources (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            kind text NOT NULL DEFAULT 'web'
                CHECK (kind IN ('article', 'book', 'report', 'web', 'standard',
                                'thesis', 'dataset', 'internal', 'other')),
            citation text NOT NULL CHECK (length(btrim(citation)) > 0),
            title text,
            authors text,
            year integer CHECK (year IS NULL OR year BETWEEN 1800 AND 2100),
            publisher text,
            doi text,
            url text,
            language text,
            notes text,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT public.app_now(),
            updated_at timestamptz NOT NULL DEFAULT public.app_now(),
            created_by uuid,
            updated_by uuid
        );
        CREATE UNIQUE INDEX uq_sources_doi ON public.sources (lower(doi)) WHERE doi IS NOT NULL;
        CREATE TRIGGER trg_sources_updated_at BEFORE UPDATE ON public.sources
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

        CREATE TABLE public.source_aliases (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            source_id uuid NOT NULL REFERENCES public.sources (id) ON DELETE CASCADE,
            document_code text NOT NULL,
            document_title text,
            ref_number integer NOT NULL CHECK (ref_number > 0),
            created_at timestamptz NOT NULL DEFAULT public.app_now(),
            UNIQUE (document_code, ref_number)
        );
        CREATE INDEX ix_source_aliases_source ON public.source_aliases (source_id);

        CREATE TABLE public.source_links (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            source_id uuid NOT NULL REFERENCES public.sources (id) ON DELETE CASCADE,
            entity_type text NOT NULL
                CHECK (entity_type IN ('finding', 'decision_tree', 'tree_parameter',
                                       'signal', 'plan_template_activity',
                                       'reference_value', 'input', 'crop_attribute')),
            entity_key text NOT NULL CHECK (length(btrim(entity_key)) > 0),
            detail text NOT NULL DEFAULT '',
            confidence text NOT NULL
                CHECK (confidence IN ('high', 'medium', 'low', 'expert_inference')),
            note text,
            created_at timestamptz NOT NULL DEFAULT public.app_now(),
            created_by uuid,
            UNIQUE (source_id, entity_type, entity_key, detail)
        );
        CREATE INDEX ix_source_links_entity ON public.source_links (entity_type, entity_key);
        """
    )
    data = json.loads(_DATA.read_text(encoding="utf-8"))
    titles: dict[str, str] = data["documents"]
    conn = op.get_bind()
    for row in data["sources"]:
        source_id = conn.execute(
            sa.text(
                "INSERT INTO public.sources (kind, citation, year, doi, url) "
                "VALUES (:kind, :citation, :year, :doi, :url) RETURNING id"
            ),
            {k: row[k] for k in ("kind", "citation", "year", "doi", "url")},
        ).scalar_one()
        for document_code, ref_number in row["aliases"]:
            conn.execute(
                sa.text(
                    "INSERT INTO public.source_aliases "
                    "(source_id, document_code, document_title, ref_number) "
                    "VALUES (:sid, :code, :title, :num)"
                ),
                {
                    "sid": source_id,
                    "code": document_code,
                    "title": titles[document_code],
                    "num": ref_number,
                },
            )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS public.source_links; "
        "DROP TABLE IF EXISTS public.source_aliases; "
        "DROP TABLE IF EXISTS public.sources;"
    )
