"""Seed `recommendation_opened` notification templates (en/ar/webhook).

Mirrors migration 0014's `alert_opened` rows so the recommendations
fan-out subscriber finds in_app/email/webhook templates the same way
the alerts fan-out does.

Variables exposed to the renderer (filled by `notifications.subscribers
._build_render_ctx_for_recommendation`):

  tenant_id, recommendation_id, block_id, block_code, farm_id, farm_name,
  tree_code, tree_name, action_type, severity, severity_label,
  text, fired_at, link_url

Webhook channel uses a JSON-shaped body; receivers parse it as a
recommendation event payload.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED: list[dict[str, object]] = [
    # ---- recommendation_opened — in-app -----------------------------------
    {
        "template_code": "recommendation_opened",
        "locale": "en",
        "channel": "in_app",
        "subject": "{{severity_label}} recommendation on block {{block_code}}",
        "body": "{{tree_name}} — {{text}}",
        "body_html": None,
    },
    {
        "template_code": "recommendation_opened",
        "locale": "ar",
        "channel": "in_app",
        "subject": "توصية {{severity_label}} على الحقل {{block_code}}",
        "body": "{{tree_name}} — {{text}}",
        "body_html": None,
    },
    # ---- recommendation_opened — email ------------------------------------
    {
        "template_code": "recommendation_opened",
        "locale": "en",
        "channel": "email",
        "subject": "[Agri.Pulse] {{severity_label}} recommendation on block {{block_code}}",
        "body": (
            "A new recommendation is available on block {{block_code}} of farm {{farm_name}}.\n\n"
            "Tree: {{tree_name}}\n"
            "Action: {{action_type}}\n"
            "Severity: {{severity_label}}\n\n"
            "{{text}}\n\n"
            "View details: {{link_url}}\n"
        ),
        "body_html": None,
    },
    {
        "template_code": "recommendation_opened",
        "locale": "ar",
        "channel": "email",
        "subject": "[أجري.بَلس] توصية {{severity_label}} على الحقل {{block_code}}",
        "body": (
            "توصية جديدة متاحة على الحقل {{block_code}} من مزرعة {{farm_name}}.\n\n"
            "الشجرة: {{tree_name}}\n"
            "الإجراء: {{action_type}}\n"
            "الخطورة: {{severity_label}}\n\n"
            "{{text}}\n\n"
            "عرض التفاصيل: {{link_url}}\n"
        ),
        "body_html": None,
    },
    # ---- recommendation_opened — webhook ---------------------------------
    # Body is the structured JSON payload. `evaluation_snapshot_json` is
    # rendered as a JSON literal (the renderer substitutes a JSON string
    # we pre-serialised in the render context).
    {
        "template_code": "recommendation_opened",
        "locale": "en",
        "channel": "webhook",
        "subject": None,
        "body": (
            '{"event":"recommendation.opened","tenant_id":"{{tenant_id}}",'
            '"recommendation_id":"{{recommendation_id}}",'
            '"block_id":"{{block_id}}","farm_id":"{{farm_id}}",'
            '"tree_code":"{{tree_code}}","action_type":"{{action_type}}",'
            '"severity":"{{severity}}","fired_at":"{{fired_at}}",'
            '"evaluation_snapshot":{{evaluation_snapshot_json}}}'
        ),
        "body_html": None,
    },
]


def upgrade() -> None:
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
    op.execute(
        sa.text(
            "DELETE FROM public.notification_templates "
            "WHERE template_code = 'recommendation_opened'"
        )
    )
    # Silence unused-import warning when rolling back without postgresql DDL.
    _ = postgresql
