"""Snapshot of a manual's activities at publish (Agri Operation PR 4).

``plan_templates.published_snapshot`` holds the manual's activities as of its
last publish, keyed by activity code. The platform editor's Publish step diffs
the current draft against it to show what changed (decision H6). Backfilled
for published manuals from their current activities, which is what farms see
today. Additive only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0107"
down_revision: str | Sequence[str] | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep in step with app.modules.plan_templates.revisions.SNAPSHOT_FIELDS.
_SNAPSHOT_SQL = """
UPDATE public.plan_templates t
SET published_snapshot = s.snap
FROM (
    SELECT a.template_id,
           jsonb_object_agg(
               a.code,
               jsonb_build_object(
                   'activity_type', a.activity_type, 'title', a.title,
                   'title_ar', a.title_ar, 'anchor', a.anchor,
                   'stage_code', a.stage_code, 'milestone_code', m.code,
                   'offset_days', a.offset_days, 'duration_days', a.duration_days,
                   'product_name', a.product_name, 'dosage', a.dosage, 'notes', a.notes,
                   'product_name_ar', a.product_name_ar, 'dosage_ar', a.dosage_ar,
                   'notes_ar', a.notes_ar, 'evidence_tier', a.evidence_tier,
                   'source_tree_code', a.source_tree_code
               )
           ) AS snap
    FROM public.plan_template_activities a
    LEFT JOIN public.plan_template_milestones m ON m.id = a.milestone_id
    GROUP BY a.template_id
) s
WHERE s.template_id = t.id AND t.status = 'published'
"""


def upgrade() -> None:
    op.add_column(
        "plan_templates",
        sa.Column("published_snapshot", postgresql.JSONB(), nullable=True),
        schema="public",
    )
    op.execute(_SNAPSHOT_SQL)


def downgrade() -> None:
    op.drop_column("plan_templates", "published_snapshot", schema="public")
