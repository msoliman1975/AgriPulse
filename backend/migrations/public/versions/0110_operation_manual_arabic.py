"""Arabic notes, products and dosages for the seeded operation manuals (Agri Operation 1b).

Fills ``notes_ar``, ``product_name_ar`` and ``dosage_ar`` (public 0104) for
the live seeded manuals so the Agri Operation screens read fully in Arabic
(decision E3): the six mango cultivars (0040; identical text), the three
potato seasons (0041; identical text) and the two organic Medjool manuals
(0099). The text is in ``data/0110_operation_manual_arabic.json``, keyed by
activity ``sort_order``.

The Medjool Arabic is a translation of the English seed, not the manual's
Arabic edition, which is not in the repository. Terms follow the manual's
Arabic edition where 0100 recorded them (e.g. «تدلية العذوق», «الذنب الأسود»,
«دفعات الجني»). Source numbers and confidence levels are kept; the
``[EG-FAO]``-style tags are left out because the evidence tier is shown on
its own.

Only empty fields are filled, so Arabic a platform author has already
written is kept. Downgrade clears only the values this migration wrote.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0110"
down_revision: str | Sequence[str] | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).parent / "data" / "0110_operation_manual_arabic.json"

FAMILIES: dict[str, tuple[str, ...]] = {
    "mango": (
        "mango-keitt-eg",
        "mango-zebda-eg",
        "mango-sukkary-eg",
        "mango-alphonso-eg",
        "mango-yasmina-eg",
        "mango-crimson-eg",
    ),
    "potato": ("potato-winter-eg", "potato-summer-eg", "potato-nili-eg"),
    "medjool_bearing": ("medjool-organic-bearing-eg",),
    "medjool_new": ("medjool-organic-new-planting-eg",),
}
_FIELDS = ("product_name_ar", "dosage_ar", "notes_ar")


def load() -> dict[str, dict[str, list[str | None]]]:
    with _DATA.open(encoding="utf-8") as f:
        data: dict[str, dict[str, list[str | None]]] = json.load(f)
    return data


def _rows():  # type: ignore[no-untyped-def]
    for family, by_sort in load().items():
        for code in FAMILIES[family]:
            for sort_order, values in by_sort.items():
                yield code, int(sort_order), dict(zip(_FIELDS, values, strict=True))


def upgrade() -> None:
    conn = op.get_bind()
    for code, sort_order, values in _rows():
        for field, value in values.items():
            if value is None:
                continue
            conn.execute(
                sa.text(
                    f"UPDATE public.plan_template_activities a SET {field} = :v "  # noqa: S608
                    "FROM public.plan_templates t "
                    "WHERE t.id = a.template_id AND t.code = :code AND t.deleted_at IS NULL "
                    f"  AND a.sort_order = :sort AND (a.{field} IS NULL OR a.{field} = '')"
                ),
                {"v": value, "code": code, "sort": sort_order},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for code, sort_order, values in _rows():
        for field, value in values.items():
            if value is None:
                continue
            conn.execute(
                sa.text(
                    f"UPDATE public.plan_template_activities a SET {field} = NULL "  # noqa: S608
                    "FROM public.plan_templates t "
                    "WHERE t.id = a.template_id AND t.code = :code "
                    f"  AND a.sort_order = :sort AND a.{field} = :v"
                ),
                {"v": value, "code": code, "sort": sort_order},
            )
