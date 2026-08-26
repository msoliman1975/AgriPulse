"""Add an Arabic name to the platform entities a tenant user reads by name.

Five `public` tables name a thing that a tenant user, or a scout on the
phone, reads on screen, and none of them had an Arabic column:

* `tenants.name`
* `plan_templates.name` / `.description`
* `plan_template_milestones.name`
* `signal_definitions.name` / `.description` / `.unit` /
  `.categorical_values`
* `signal_templates.name` / `.description`

`signal_definitions.categorical_values` matters most. It is a plain text
array, so a scout picking a value in the Arabic app was reading
`emitter_blocked` and `powdery`. The new `categorical_values_ar` is a
parallel array: same length, same order, one Arabic label per code. A
CHECK enforces the equal length, because a shorter Arabic array would
show a blank option rather than fail.

Every column is nullable and readers fall back with
`COALESCE(NULLIF(x_ar, ''), x)`. During a rolling deploy an older API
image writes NULL, and the fallback is what keeps those rows readable.

Backfill, in two passes:

1. Copy the English value into the Arabic column for every row. This is
   a placeholder, not a translation. A tenant's own name and a plan
   template's cultivar name cannot be machine translated here, and an
   empty column would show a blank name on the Arabic pages.
2. Overwrite the nine platform scouting signal definitions and the five
   platform templates from migration 0053 with real Arabic, including
   every categorical value. That vocabulary is the scouting app's whole
   form language, it is fixed, and it is written once here.

Pass 2 only touches platform rows (`tenant_id IS NULL`) whose current
name still equals the English seed value. A platform admin who has
already renamed one keeps their edit.

Down drops the columns and the CHECK.

Revision ID: 0075
Revises: 0074
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0075"
down_revision: str | Sequence[str] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, source column to copy from)
_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("tenants", "name_ar", "name"),
    ("plan_templates", "name_ar", "name"),
    ("plan_templates", "description_ar", "description"),
    ("plan_template_milestones", "name_ar", "name"),
    ("signal_definitions", "name_ar", "name"),
    ("signal_definitions", "description_ar", "description"),
    ("signal_definitions", "unit_ar", "unit"),
    ("signal_templates", "name_ar", "name"),
    ("signal_templates", "description_ar", "description"),
)


# code -> (english name, arabic name, arabic description,
#          {english categorical value: arabic label})
_SIGNAL_AR: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "canopy_vigour": (
        "Canopy vigour",
        "قوة المجموع الخضري",
        "الحالة الظاهرية العامة للمجموع الخضري عند نقطة الفحص.",
        {"good": "جيد", "fair": "متوسط", "poor": "ضعيف", "severe": "ضعيف جدا"},
    ),
    "stress_cause_observed": (
        "Observed cause of stress",
        "سبب الإجهاد الملاحظ",
        "السبب الذي ينسب إليه المرشد الإجهاد. الخيار «لا يوجد» إجابة صحيحة، "
        "وبه يسجل الإنذار الخاطئ.",
        {
            "water": "المياه",
            "pest": "آفة",
            "disease": "مرض",
            "nutrition": "التغذية",
            "salinity": "الملوحة",
            "mechanical": "ضرر ميكانيكي",
            "none": "لا يوجد",
            "unknown": "غير معروف",
        },
    ),
    "pest_incidence_pct": (
        "Pest incidence",
        "نسبة الإصابة بالآفات",
        "نسبة النباتات المفحوصة التي تظهر عليها أضرار الآفات.",
        {},
    ),
    "disease_symptom": (
        "Disease symptom",
        "عرض المرض",
        "العرض الملاحظ، وليس التشخيص. التشخيص يتم في خطوة لاحقة.",
        {
            "leaf_spot": "تبقع الأوراق",
            "powdery": "البياض الدقيقي",
            "anthracnose": "الأنثراكنوز",
            "wilt": "الذبول",
            "chlorosis": "اصفرار الأوراق",
            "necrosis": "تنخر الأنسجة",
            "none": "لا يوجد",
        },
    ),
    "disease_severity": (
        "Disease severity",
        "شدة الإصابة",
        "مدى تقدم العرض في المكان الذي وجد فيه.",
        {
            "none": "لا يوجد",
            "trace": "أثر بسيط",
            "moderate": "متوسطة",
            "severe": "شديدة",
        },
    ),
    "soil_moisture_feel": (
        "Soil moisture (by feel)",
        "رطوبة التربة بالجس",
        "تقدير باللمس على عمق الجذور. التقدير تقريبي عن قصد، فهو مراجعة " "للري وليس قياسا.",
        {"dry": "جافة", "moist": "رطبة", "wet": "مبتلة", "saturated": "مشبعة"},
    ),
    "irrigation_fault": (
        "Irrigation fault",
        "عطل في الري",
        "عطل ظاهر في شبكة الري التي تخدم هذه القطعة.",
        {
            "none": "لا يوجد",
            "emitter_blocked": "نقاط تنقيط مسدودة",
            "line_leak": "تسريب في الخط",
            "no_pressure": "لا يوجد ضغط",
            "uneven": "توزيع غير متساو",
        },
    ),
    "weed_pressure": (
        "Weed pressure",
        "كثافة الحشائش",
        "المنافسة الملاحظة أثناء جولة اعتيادية.",
        {"none": "لا يوجد", "light": "خفيفة", "moderate": "متوسطة", "heavy": "كثيفة"},
    ),
    "scout_photo": (
        "Scout photo",
        "صورة من المرشد الحقلي",
        "صورة تلتقط أثناء الزيارة. كل صورة ملاحظة مستقلة تحمل الموقع والوقت "
        "لحظة التقاط الصورة، وليس وقت الإرسال.",
        {},
    ),
}

# code -> (english name, arabic name, arabic description)
_TEMPLATE_AR: tuple[tuple[str, str, str, str], ...] = (
    (
        "scout_general_v1",
        "General scouting visit",
        "زيارة إرشادية عامة",
        "النموذج الافتراضي لزيارة ناتجة عن توصية أو إنذار.",
    ),
    (
        "scout_pest_disease_v1",
        "Pest and disease inspection",
        "فحص الآفات والأمراض",
        "للزيارات الصادرة عن إشارة آفة أو مرض.",
    ),
    (
        "scout_irrigation_v1",
        "Irrigation check",
        "فحص الري",
        "للزيارات الناتجة عن إشارات الري أو إجهاد المياه.",
    ),
    (
        "scout_routine_v1",
        "Routine round",
        "جولة اعتيادية",
        "جولة مجدولة، وليست استجابة لإشارة.",
    ),
    (
        "scout_quick_v1",
        "Quick log",
        "تسجيل سريع",
        "جولة يبدأها المرشد: صورة وملاحظة فقط.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    for table, column, source in _ADDITIONS:
        op.add_column(table, sa.Column(column, sa.Text(), nullable=True), schema="public")
        op.execute(
            sa.text(
                f"UPDATE public.{table} SET {column} = {source} "  # noqa: S608
                f"WHERE {source} IS NOT NULL AND {column} IS NULL"
            )
        )

    op.add_column(
        "signal_definitions",
        sa.Column("categorical_values_ar", postgresql.ARRAY(sa.Text()), nullable=True),
        schema="public",
    )
    op.execute(
        sa.text(
            "UPDATE public.signal_definitions SET categorical_values_ar = categorical_values "
            "WHERE categorical_values IS NOT NULL AND categorical_values_ar IS NULL"
        )
    )
    op.create_check_constraint(
        "ck_signal_definitions_categorical_ar_length",
        "signal_definitions",
        "categorical_values_ar IS NULL "
        "OR categorical_values IS NULL "
        "OR array_length(categorical_values_ar, 1) IS NOT DISTINCT FROM "
        "array_length(categorical_values, 1)",
        schema="public",
    )

    # ---- Pass 2: the real Arabic for the platform scouting catalog ---------
    for code, (name_en, name_ar, description_ar, values_ar) in _SIGNAL_AR.items():
        row = bind.execute(
            sa.text(
                "SELECT categorical_values FROM public.signal_definitions "
                "WHERE code = :code AND tenant_id IS NULL AND name = :name_en "
                "AND deleted_at IS NULL"
            ),
            {"code": code, "name_en": name_en},
        ).first()
        if row is None:
            # Renamed by a platform admin, or never seeded. Pass 1 already
            # left a readable English placeholder; leave the edit alone.
            continue
        # Map value-by-value rather than writing a fixed array, so the order
        # follows whatever the row actually holds and a value with no Arabic
        # label falls back to its own code instead of shifting the array.
        current = list(row[0] or [])
        translated = [values_ar.get(v, v) for v in current] if current else None
        bind.execute(
            sa.text(
                "UPDATE public.signal_definitions "
                "   SET name_ar = :name_ar, "
                "       description_ar = :description_ar, "
                "       categorical_values_ar = CAST(:values_ar AS text[]) "
                " WHERE code = :code AND tenant_id IS NULL AND deleted_at IS NULL"
            ),
            {
                "code": code,
                "name_ar": name_ar,
                "description_ar": description_ar,
                "values_ar": translated,
            },
        )

    for code, name_en, name_ar, description_ar in _TEMPLATE_AR:
        bind.execute(
            sa.text(
                "UPDATE public.signal_templates "
                "   SET name_ar = :name_ar, description_ar = :description_ar "
                " WHERE code = :code AND tenant_id IS NULL AND name = :name_en "
                "   AND deleted_at IS NULL"
            ),
            {
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "description_ar": description_ar,
            },
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_signal_definitions_categorical_ar_length",
        "signal_definitions",
        schema="public",
        type_="check",
    )
    op.drop_column("signal_definitions", "categorical_values_ar", schema="public")
    for table, column, _source in reversed(_ADDITIONS):
        op.drop_column(table, column, schema="public")
