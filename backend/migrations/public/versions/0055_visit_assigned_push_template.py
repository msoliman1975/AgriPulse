"""Push copy for "a visit is yours" (S2).

The alert and recommendation pushes say what the satellite saw. This one says
what the person has to do, which is a different sentence: the subject leads
with the block and the deadline, because those are the two facts that decide
whether a scout walks now or after lunch.

``{{instruction}}`` renders only for ad-hoc visits, where a supervisor typed
something. Everywhere else the body falls back to the visit title, so the copy
never shows an empty gap where a human sentence would be.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "scouting_visit_assigned"

_ROWS: tuple[tuple[str, str, str], ...] = (
    # (locale, subject, body)
    ("en", "Scouting visit — due in {{due_in}}", "{{title}}"),
    ("ar", "زيارة فحص — خلال {{due_in}}", "{{title}}"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for locale, subject, body in _ROWS:
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
            {"code": _CODE, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM public.notification_templates "
            "WHERE template_code = :code AND channel = 'push' AND version = 1"
        ),
        {"code": _CODE},
    )
