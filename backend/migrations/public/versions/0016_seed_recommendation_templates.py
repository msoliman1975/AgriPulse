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
    # ---- recommendation_opened â€” in-app -----------------------------------
    {
        "template_code": "recommendation_opened",
        "locale": "en",
        "channel": "in_app",
        "subject": "{{severity_label}} recommendation on block {{block_code}}",
        "body": "{{tree_name}} â€” {{text}}",
        "body_html": None,
    },
    {
        "template_code": "recommendation_opened",
        "locale": "ar",
        "channel": "in_app",
        "subject": "ØªÙˆØµÙŠØ© {{severity_label}} Ø¹Ù„Ù‰ Ø§Ù„Ø­Ù‚Ù„ {{block_code}}",
        "body": "{{tree_name}} â€” {{text}}",
        "body_html": None,
    },
    # ---- recommendation_opened â€” email ------------------------------------
    {
        "template_code": "recommendation_opened",
        "locale": "en",
        "channel": "email",
        "subject": "[AgriPulse] {{severity_label}} recommendation on block {{block_code}}",
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
        "subject": "[Ø£Ø¬Ø±ÙŠ.Ø¨ÙŽÙ„Ø³] ØªÙˆØµÙŠØ© {{severity_label}} Ø¹Ù„Ù‰ Ø§Ù„Ø­Ù‚Ù„ {{block_code}}",
        "body": (
            "ØªÙˆØµÙŠØ© Ø¬Ø¯ÙŠØ¯Ø© Ù…ØªØ§Ø­Ø© Ø¹Ù„Ù‰ Ø§Ù„Ø­Ù‚Ù„ {{block_code}} Ù…Ù† Ù…Ø²Ø±Ø¹Ø© {{farm_name}}.\n\n"
            "Ø§Ù„Ø´Ø¬Ø±Ø©: {{tree_name}}\n"
            "Ø§Ù„Ø¥Ø¬Ø±Ø§Ø¡: {{action_type}}\n"
            "Ø§Ù„Ø®Ø·ÙˆØ±Ø©: {{severity_label}}\n\n"
            "{{text}}\n\n"
            "Ø¹Ø±Ø¶ Ø§Ù„ØªÙØ§ØµÙŠÙ„: {{link_url}}\n"
        ),
        "body_html": None,
    },
    # ---- recommendation_opened â€” webhook ---------------------------------
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
