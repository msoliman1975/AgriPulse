"""Push templates for the alert and recommendation channels (S2).

Without these, every push records ``status='failed', error='template not
found'`` — the fan-out looks up a template per (code, locale, channel) and the
push channel had none.

Push copy is not email copy with the greeting removed. A notification is read
in one glance, on a lock screen, possibly in sunlight, by someone who has to
decide in that moment whether to walk to a field. So the subject leads with
*where* rather than with the severity word, and the body says what to do rather
than restating the title.

Both locales, because the app is Arabic-first and a push rendered in English
for an Arabic-speaking scout is worse than no push at all — it is a
notification they must ask someone to read.

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (template_code, locale, subject, body) — variables match the render context
# built in notifications/subscribers.py::_build_render_ctx.
_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "alert_opened",
        "en",
        "{{block_code}} — {{severity_label}}",
        "{{diagnosis}}",
    ),
    (
        "alert_opened",
        "ar",
        "{{block_code}} — {{severity_label}}",
        "{{diagnosis}}",
    ),
    (
        "recommendation_opened",
        "en",
        "{{block_code}} — {{severity_label}}",
        "{{text}}",
    ),
    (
        "recommendation_opened",
        "ar",
        "{{block_code}} — {{severity_label}}",
        "{{text}}",
    ),
)


# Real constraint names, read from pg_constraint rather than reconstructed:
# Alembic's naming convention already applied a `ck_<table>_` prefix to a
# constraint whose own name carried it too, so both are doubled on disk.
_CHANNELS = "'in_app', 'email', 'webhook', 'push'"


def _channel_ck_name(table: str, schema: str | None = None) -> str:
    """Look the channel CHECK's real name up in the catalog.

    Never reconstruct it. The name on disk is already doubled (the convention
    prefixed a constraint whose own name carried the prefix), and passing that
    full name back to ``create_check_constraint`` prefixes it a third time and
    overflows Postgres' 63-character limit into a hash suffix. Reading it means
    the migration works whatever shape a given database ended up with.
    """
    bind = op.get_bind()
    qualified = f"{schema}.{table}" if schema else table
    return str(
        bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:rel AS regclass) AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%channel%' LIMIT 1"
            ),
            {"rel": qualified},
        ).scalar_one()
    )


def upgrade() -> None:
    bind = op.get_bind()
    # Widen the channel vocabulary before inserting: the CHECK predates the
    # push channel and would reject every row below.
    op.drop_constraint(
        _channel_ck_name("notification_templates", "public"),
        "notification_templates",
        schema="public",
    )
    # Short name: the convention expands it to `ck_notification_templates_channel`.
    op.create_check_constraint(
        "channel", "notification_templates", f"channel IN ({_CHANNELS})", schema="public"
    )
    for template_code, locale, subject, body in _TEMPLATES:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.notification_templates
                       (template_code, locale, channel, version, subject, body)
                SELECT :code, :locale, 'push', 1, :subject, :body
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.notification_templates
                     WHERE template_code = :code AND locale = :locale
                       AND channel = 'push' AND version = 1
                 )
                """
            ),
            {"code": template_code, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM public.notification_templates "
            "WHERE channel = 'push' AND version = 1 "
            "AND template_code IN ('alert_opened', 'recommendation_opened')"
        )
    )
    op.drop_constraint(
        _channel_ck_name("notification_templates", "public"),
        "notification_templates",
        schema="public",
    )
    op.create_check_constraint(
        "channel",
        "notification_templates",
        "channel IN ('in_app', 'email', 'webhook')",
        schema="public",
    )
