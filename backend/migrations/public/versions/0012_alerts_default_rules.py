"""default_rules catalog — platform-curated rule library for the alerts engine.

PR-5 of FarmDM rollout. The agronomy engine is two-layered:

  * `public.default_rules` — platform-managed catalog. Rule code,
    name, severity, status, applies-to filter, and JSONB conditions +
    actions. Seeded with a starter set; admins extend via SQL until the
    first admin UI lands.
  * `tenant.rule_overrides` (in tenant migration 0009) — per-tenant
    customisation: enable/disable, severity tweak, conditions/actions
    overrides. The engine merges the override on top of the default at
    evaluation time.

Conditions JSONB shape (MVP):

  {
    "type": "baseline_deviation_below",
    "index_code": "ndvi",
    "threshold": -1.5
  }

Actions JSONB shape:

  {
    "diagnosis_en": "...", "diagnosis_ar": "...",
    "prescription_en": "...", "prescription_ar": "..."
  }

The engine dispatches on ``conditions.type``; new predicate kinds
arrive by adding a handler in ``app.modules.alerts.engine`` and a row
that uses the new type. Older rule rows keep working unchanged.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED_RULES: list[dict[str, object]] = [
    {
        "code": "ndvi_severe_drop",
        "name_en": "NDVI severely below historical baseline",
        "name_ar": "تراجع حاد في NDVI عن المتوسط التاريخي",
        "description_en": (
            "Latest NDVI mean is more than 1.5 standard deviations below the "
            "block's own seasonal baseline — a strong indicator of stress."
        ),
        "description_ar": (
            "متوسط NDVI الحالي أقل من المعدل الموسمي بأكثر من 1.5 انحراف معياري — "
            "مؤشر قوي على وجود إجهاد على المحصول."
        ),
        "severity": "critical",
        "applies_to_crop_categories": [],
        "conditions": {
            "type": "baseline_deviation_below",
            "index_code": "ndvi",
            "threshold": -1.5,
        },
        "actions": {
            "diagnosis_en": (
                "NDVI is significantly below the block's historical baseline for this "
                "time of year. Common causes: water stress, pest/disease pressure, "
                "nutrient deficiency, or recent damage."
            ),
            "diagnosis_ar": (
                "NDVI أقل بشكل ملحوظ من معدل الحقل التاريخي لهذا الوقت من السنة. "
                "أسباب شائعة: إجهاد مائي، إصابات، نقص عناصر، أو ضرر حديث."
            ),
            "prescription_en": (
                "Schedule a field inspection within 48 hours. Verify irrigation, "
                "scout for pests/disease, and check the latest soil moisture readings."
            ),
            "prescription_ar": (
                "حدّد زيارة حقلية خلال 48 ساعة. تحقق من الري، فحص الآفات والأمراض، "
                "وراجع آخر قراءات رطوبة التربة."
            ),
        },
    },
    {
        "code": "ndvi_warning_drop",
        "name_en": "NDVI below historical baseline",
        "name_ar": "تراجع NDVI عن المتوسط التاريخي",
        "description_en": (
            "Latest NDVI mean is between 0.75 and 1.5 standard deviations below "
            "baseline — a watch-list signal that warrants attention."
        ),
        "description_ar": (
            "متوسط NDVI الحالي أقل من المعدل التاريخي بنسبة بين 0.75 و 1.5 انحراف "
            "معياري — مؤشر تحذيري يستوجب المتابعة."
        ),
        "severity": "warning",
        "applies_to_crop_categories": [],
        "conditions": {
            "type": "baseline_deviation_between",
            "index_code": "ndvi",
            "low": -1.5,
            "high": -0.75,
        },
        "actions": {
            "diagnosis_en": (
                "NDVI is trending below the historical baseline. Not yet severe, but "
                "worth a closer look."
            ),
            "diagnosis_ar": "NDVI يتراجع عن المعدل التاريخي. ليس حادًا بعد، لكنه يستحق المتابعة.",
            "prescription_en": (
                "Add the block to your next routine scouting round; review the trend "
                "chart for the past two weeks."
            ),
            "prescription_ar": (
                "أضف الحقل إلى جولة الفحص الروتينية التالية؛ راجع منحنى الاتجاه لآخر " "أسبوعين."
            ),
        },
    },
]


def upgrade() -> None:
    op.create_table(
        "default_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'warning'"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "applies_to_crop_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_default_rules_severity",
        "default_rules",
        "severity IN ('info', 'warning', 'critical')",
        schema="public",
    )
    op.create_check_constraint(
        "ck_default_rules_status",
        "default_rules",
        "status IN ('active', 'draft', 'retired')",
        schema="public",
    )
    op.create_index(
        "ix_default_rules_status",
        "default_rules",
        ["status"],
        schema="public",
        postgresql_where=sa.text("status = 'active'"),
    )

    # Seed the starter ruleset. Idempotent via ON CONFLICT — re-running
    # the migration after deleting a row is operationally a no-op.
    rules_table = sa.table(
        "default_rules",
        sa.column("code", sa.Text()),
        sa.column("name_en", sa.Text()),
        sa.column("name_ar", sa.Text()),
        sa.column("description_en", sa.Text()),
        sa.column("description_ar", sa.Text()),
        sa.column("severity", sa.Text()),
        sa.column("applies_to_crop_categories", postgresql.ARRAY(sa.Text())),
        sa.column("conditions", postgresql.JSONB()),
        sa.column("actions", postgresql.JSONB()),
        schema="public",
    )
    # Pass dicts directly — SQLAlchemy's JSONB column type binds them
    # as JSONB. ``json.dumps`` would send a JSON-string literal that
    # asyncpg later returns as ``str`` on read, breaking the engine's
    # ``conditions.get("type")`` dispatch.
    op.bulk_insert(
        rules_table,
        [
            {
                "code": rule["code"],
                "name_en": rule["name_en"],
                "name_ar": rule["name_ar"],
                "description_en": rule["description_en"],
                "description_ar": rule["description_ar"],
                "severity": rule["severity"],
                "applies_to_crop_categories": rule["applies_to_crop_categories"],
                "conditions": rule["conditions"],
                "actions": rule["actions"],
            }
            for rule in _SEED_RULES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_default_rules_status", table_name="default_rules", schema="public")
    op.drop_constraint("ck_default_rules_status", "default_rules", schema="public", type_="check")
    op.drop_constraint("ck_default_rules_severity", "default_rules", schema="public", type_="check")
    op.drop_table("default_rules", schema="public")
