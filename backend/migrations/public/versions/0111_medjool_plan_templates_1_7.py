"""The Organic Medjool plan templates for manual Edition 1.7, as drafts (D13).

Decided 2026-11-11: publish 1.7 as new templates and archive the 1.3 ones
(``medjool-organic-bearing-eg`` and ``medjool-organic-new-planting-eg``,
public 0099). This migration only adds the two 1.7 templates as **drafts**;
publishing them and archiving the 1.3 ones go through the API afterwards, so
the platform's publish step writes the snapshot and the audit trail.

The content is in ``data/0111_medjool_plan_templates_1_7.json``: every 1.3
activity re-checked against 1.7 (sections 12.2 and 8.8), plus the new 1.7
tasks. Each activity keeps its 1.3 code where it continues, carries English
and the manual's Arabic edition, ``evidence_tier = 'manual'``, a catalogue
input and structured dose where the manual names one (public 0108/0109), and
links to the manual's sources (public 0105) under ``plan_template_activity``
with the key ``<template code>/<activity code>``.

Bearing activities are anchored to the nine Medjool stages; their notes are
prefixed "Week N." / "Weeks N-M." as in 0099. New-planting activities are
anchored on the plan start, the field planting week.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0111"
down_revision: str | Sequence[str] | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).parent / "data" / "0111_medjool_plan_templates_1_7.json"
_PATH = "date_palm.medjool"
_DOCUMENT = "medjool_manual_1_7"

TEMPLATES: dict[str, dict[str, Any]] = {
    "medjool-organic-bearing-eg-1-7": {
        "key": "bearing",
        "name": "Organic Medjool 1.7 - bearing palms (Western Desert, Egypt)",
        "name_ar": "المجدول العضوي 1.7 - النخيل المثمر (الصحراء الغربية، مصر)",
        "description": (
            "52-week plan from the Organic Medjool Manual, Edition 1.7, section 12. "
            "Activities follow the nine Medjool stages. Repeated work is one activity per "
            "window with the frequency in its notes. Replaces the Edition 1.3 plan."
        ),
        "description_ar": (
            "خطة 52 أسبوعًا من دليل المجدول العضوي، الإصدار 1.7، القسم 12. "
            "تتبع الأنشطة مراحل المجدول التسع. تحل محل خطة الإصدار 1.3."
        ),
    },
    "medjool-organic-new-planting-eg-1-7": {
        "key": "new_planting",
        "name": "Organic Medjool 1.7 - new planting to first fruit (Western Desert, Egypt)",
        "name_ar": "المجدول العضوي 1.7 - من الزراعة حتى بداية الإثمار (الصحراء الغربية، مصر)",
        "description": (
            "From before planting to the onset of fruiting, from the Organic Medjool Manual, "
            "Edition 1.7, section 8.8. Set the plan start date to the field planting week. "
            "Replaces the Edition 1.3 plan."
        ),
        "description_ar": (
            "من قبل الزراعة حتى بداية الإثمار، من دليل المجدول العضوي، الإصدار 1.7، "
            "القسم 8.8. اجعل تاريخ بداية الخطة أسبوع الزراعة في الحقل. "
            "تحل محل خطة الإصدار 1.3."
        ),
    },
}


def load() -> dict[str, list[dict[str, Any]]]:
    with _DATA.open(encoding="utf-8") as f:
        data: dict[str, list[dict[str, Any]]] = json.load(f)
    return data


def _week_prefix(first: int, last: int) -> str:
    return f"Week {first}." if first == last else f"Weeks {first}-{last}."


def _week_prefix_ar(first: int, last: int) -> str:
    return f"الأسبوع {first}." if first == last else f"الأسابيع {first}-{last}."


def activity_rows(key: str) -> list[dict[str, Any]]:
    """The rows to insert for one template, in plan order."""
    rows = []
    for sort, a in enumerate(load()[key], 1):
        notes, notes_ar = a["notes"], a.get("notes_ar")
        if key == "bearing":
            notes = f"{_week_prefix(a['first_week'], a['last_week'])} {notes}"
            if notes_ar:
                notes_ar = f"{_week_prefix_ar(a['first_week'], a['last_week'])} {notes_ar}"
        rows.append(
            {
                "code": a["code"],
                "activity_type": a["activity_type"],
                "title": a["title"],
                "title_ar": a.get("title_ar"),
                "anchor": "stage" if key == "bearing" else "start",
                "stage_code": a.get("stage_code") if key == "bearing" else None,
                "offset_days": a["offset_days"],
                "duration_days": a["duration_days"],
                "product_name": a.get("product_name"),
                "product_name_ar": a.get("product_name_ar"),
                "dosage": a.get("dosage"),
                "dosage_ar": a.get("dosage_ar"),
                "notes": notes,
                "notes_ar": notes_ar,
                "input_code": a.get("input_code"),
                "dose_value": a.get("dose_value"),
                "dose_value_max": a.get("dose_value_max"),
                "dose_unit": a.get("dose_unit"),
                "source_tree_code": a.get("source_tree_code"),
                "source_refs": list(a.get("source_refs") or []),
                "confidence": a.get("confidence") or "medium",
                "manual_section": a.get("manual_section") or "",
                "sort_order": sort,
            }
        )
    return rows


def upgrade() -> None:
    conn = op.get_bind()
    crop_id = conn.execute(
        sa.text("SELECT id FROM public.crops WHERE code = 'date_palm' AND deleted_at IS NULL")
    ).scalar()
    if crop_id is None:
        return
    for code, meta in TEMPLATES.items():
        exists = conn.execute(
            sa.text("SELECT 1 FROM public.plan_templates WHERE code = :c AND deleted_at IS NULL"),
            {"c": code},
        ).first()
        if exists is not None:
            continue
        template_id = conn.execute(
            sa.text(
                "INSERT INTO public.plan_templates "
                "(code, name, name_ar, crop_path, crop_id, country, region, description, "
                " description_ar, status) "
                "VALUES (:code, :name, :name_ar, :path, :crop_id, 'EG', NULL, :description, "
                " :description_ar, 'draft') RETURNING id"
            ),
            {
                "code": code,
                "path": _PATH,
                "crop_id": crop_id,
                **{k: v for k, v in meta.items() if k != "key"},
            },
        ).scalar_one()
        for row in activity_rows(meta["key"]):
            input_id = None
            if row["input_code"]:
                input_id = conn.execute(
                    sa.text("SELECT id FROM public.inputs WHERE code = :c AND tenant_id IS NULL"),
                    {"c": row["input_code"]},
                ).scalar()
            conn.execute(
                sa.text(
                    "INSERT INTO public.plan_template_activities "
                    "(template_id, code, activity_type, title, title_ar, anchor, milestone_id, "
                    " stage_code, offset_days, duration_days, product_name, product_name_ar, "
                    " dosage, dosage_ar, notes, notes_ar, input_id, dose_value, dose_value_max, "
                    " dose_unit, evidence_tier, source_tree_code, sort_order) "
                    "VALUES (:tid, :code, :activity_type, :title, :title_ar, :anchor, NULL, "
                    " :stage_code, :offset_days, :duration_days, :product_name, "
                    " :product_name_ar, :dosage, :dosage_ar, :notes, :notes_ar, :input_id, "
                    " :dose_value, :dose_value_max, :dose_unit, 'manual', :source_tree_code, "
                    " :sort_order)"
                ),
                {"tid": template_id, "input_id": input_id, **row},
            )
            for ref in row["source_refs"]:
                conn.execute(
                    sa.text(
                        "INSERT INTO public.source_links "
                        "(source_id, entity_type, entity_key, detail, confidence) "
                        "SELECT a.source_id, 'plan_template_activity', :key, :detail, :conf "
                        "FROM public.source_aliases a "
                        "WHERE a.document_code = :doc AND a.ref_number = :ref "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "key": f"{code}/{row['code']}",
                        "detail": row["manual_section"],
                        "conf": row["confidence"],
                        "doc": _DOCUMENT,
                        "ref": ref,
                    },
                )


def downgrade() -> None:
    conn = op.get_bind()
    codes = list(TEMPLATES)
    conn.execute(
        sa.text(
            "DELETE FROM public.source_links WHERE entity_type = 'plan_template_activity' "
            "AND split_part(entity_key, '/', 1) = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))),
        {"codes": codes},
    )
    conn.execute(
        sa.text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))
        ),
        {"codes": codes},
    )
