"""notification_templates — platform-curated rendered text per (code, locale, channel).

PR-S4-B of Slice 4. The notifications module renders one of these
rows when fanning out an alert/recommendation across channels. Like
``default_rules``, the catalog is platform-managed and immutable from
the tenant side; rule_code seeds + tenant overrides will follow if
per-tenant template customisation is ever needed (deferred to P2).

Primary key is (template_code, locale, channel, version) so a template
can be revised by inserting a new version row instead of mutating the
old one — older alerts retain the wording that fired with them.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED: list[dict[str, object]] = [
    # ---- alert_opened ----------------------------------------------------
    {
        "template_code": "alert_opened",
        "locale": "en",
        "channel": "in_app",
        "subject": "{{severity_label}} alert on block {{block_code}}",
        "body": "{{rule_name}} — {{diagnosis}}",
        "body_html": None,
    },
    {
        "template_code": "alert_opened",
        "locale": "ar",
        "channel": "in_app",
        "subject": "تنبيه {{severity_label}} على الحقل {{block_code}}",
        "body": "{{rule_name}} — {{diagnosis}}",
        "body_html": None,
    },
    {
        "template_code": "alert_opened",
        "locale": "en",
        "channel": "email",
        "subject": "[Agri.Pulse] {{severity_label}} alert on block {{block_code}}",
        "body": (
            "An alert just fired on block {{block_code}} of farm {{farm_name}}.\n\n"
            "Rule: {{rule_name}}\n"
            "Severity: {{severity_label}}\n\n"
            "Diagnosis:\n{{diagnosis}}\n\n"
            "Recommended action:\n{{prescription}}\n\n"
            "View details: {{link_url}}\n"
        ),
        "body_html": None,
    },
    {
        "template_code": "alert_opened",
        "locale": "ar",
        "channel": "email",
        "subject": "[أجري.بَلس] تنبيه {{severity_label}} على الحقل {{block_code}}",
        "body": (
            "صدر تنبيه جديد على الحقل {{block_code}} من مزرعة {{farm_name}}.\n\n"
            "القاعدة: {{rule_name}}\n"
            "الخطورة: {{severity_label}}\n\n"
            "التشخيص:\n{{diagnosis}}\n\n"
            "الإجراء المقترح:\n{{prescription}}\n\n"
            "عرض التفاصيل: {{link_url}}\n"
        ),
        "body_html": None,
    },
    # Webhook: no localization; body is the JSON payload contract.
    {
        "template_code": "alert_opened",
        "locale": "en",
        "channel": "webhook",
        "subject": None,
        "body": (
            '{"event":"alert.opened","tenant_id":"{{tenant_id}}",'
            '"alert_id":"{{alert_id}}","block_id":"{{block_id}}",'
            '"rule_code":"{{rule_code}}","severity":"{{severity}}",'
            '"fired_at":"{{fired_at}}","signal_snapshot":{{signal_snapshot_json}}}'
        ),
        "body_html": None,
    },
]


def upgrade() -> None:
    op.create_table(
        "notification_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("template_code", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
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
        sa.PrimaryKeyConstraint("template_code", "locale", "channel", "version"),
        sa.UniqueConstraint("id"),
        schema="public",
    )
    op.create_check_constraint(
        "ck_notification_templates_channel",
        "notification_templates",
        "channel IN ('in_app', 'email', 'webhook')",
        schema="public",
    )

    table = sa.table(
        "notification_templates",
        sa.column("template_code", sa.Text()),
        sa.column("locale", sa.Text()),
        sa.column("channel", sa.Text()),
        sa.column("subject", sa.Text()),
        sa.column("body", sa.Text()),
        sa.column("body_html", sa.Text()),
        schema="public",
    )
    op.bulk_insert(table, _SEED)


def downgrade() -> None:
    op.drop_constraint(
        "ck_notification_templates_channel",
        "notification_templates",
        schema="public",
        type_="check",
    )
    op.drop_table("notification_templates", schema="public")
