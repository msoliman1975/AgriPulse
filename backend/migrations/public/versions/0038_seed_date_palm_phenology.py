"""Seed phenology stages + size classes for date palm (perennial), Egypt.

Date palm (Phoenix dactylifera) already exists (migration 0006) at
``classification_depth='variety'`` (set crop-wide by 0030). This migration
adds a crop-level ``phenology_stages`` calendar (calendar_doy windows for
Egypt) and ``size_classes`` so stage-anchored plan templates resolve for
every date-palm block regardless of cultivar.

Stage windows are anchored to the verified date-palm ripening sequence
(Hababouk 4-5 wk → Kimri 9-14 wk → Khalal 3-5 wk → Rutab 2-4 wk → Tamar
2-4 wk; Frontiers Sust. Food Syst. 2025, 3-vote verified) plus the Egyptian
pollination window (female spathe cracking late-Feb/Mar; Al-Wasfy Zaghloul
study). Operational defaults for soft/semi-dry mid-season cultivars; dry
cultivars (e.g. Siwi) ripen later. Editable via the catalog — not calibrated
study values. Non-overlapping, covers all 12 months so the auto-advance
task always resolves a stage. Idempotent: re-running upserts the same rows.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stage(code: str, en: str, ar: str, order: int, start: str, end: str) -> dict:
    return {
        "code": code,
        "name_en": en,
        "name_ar": ar,
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


# Crop-level date-palm cycle (generic Egyptian soft/semi-dry cultivar).
_DATE_PALM_STAGES = {
    "stages": [
        _stage(
            "dormancy", "Winter dormancy / pruning", "السكون الشتوي / التقليم", 1, "12-01", "02-15"
        ),
        _stage(
            "pollination",
            "Spathe emergence & pollination",
            "خروج الطلع والتلقيح",
            2,
            "02-16",
            "03-31",
        ),
        _stage("fruit_set", "Fruit set (Hababouk)", "العقد (الحبابوك)", 3, "04-01", "04-30"),
        _stage("kimri", "Kimri (green growth)", "الكمري (النمو الأخضر)", 4, "05-01", "07-15"),
        _stage("khalal", "Khalal (colour / sizing)", "الخلال (التلوين)", 5, "07-16", "08-31"),
        _stage("rutab", "Rutab (soft ripe)", "الرطب", 6, "09-01", "09-30"),
        _stage(
            "tamar", "Tamar (cured) / post-harvest", "التمر / ما بعد الحصاد", 7, "10-01", "11-30"
        ),
    ]
}

_DATE_PALM_SIZE_CLASSES = {
    "classes": [
        {"code": "young", "name_en": "Young (<5 m)", "name_ar": "صغير (<5 م)", "order": 1},
        {"code": "mature", "name_en": "Mature (5-10 m)", "name_ar": "مثمر (5-10 م)", "order": 2},
        {"code": "tall", "name_en": "Tall (>10 m)", "name_ar": "عالي (>10 م)", "order": 3},
    ]
}


def upgrade() -> None:
    op.get_bind().execute(
        text(
            "UPDATE public.crops SET "
            " phenology_stages = CAST(:stages AS jsonb), "
            " size_classes = CAST(:sizes AS jsonb) "
            "WHERE code = 'date_palm'"
        ),
        {
            "stages": json.dumps(_DATE_PALM_STAGES),
            "sizes": json.dumps(_DATE_PALM_SIZE_CLASSES),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(
        text(
            "UPDATE public.crops SET phenology_stages = NULL, size_classes = NULL "
            "WHERE code = 'date_palm'"
        )
    )
