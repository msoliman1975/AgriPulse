"""The farm's own health definition, and the lock that freezes it.

Phase 6 of moving block health off NDVI thresholds. Phase 5 gave a crop its
own values; this gives a farm the last word.

**Health is a resolution tier, not a template.** That is the difference from
every other farm-config category and it is what this migration's shape says.
`subscriptions`, `irrigation`, `org` and `grid` are templates: the farm holds
a wanted state, blocks hold their own copies, and an explicit Apply
reconciles the two — which is why each of them has a diff, a preview, and a
lock that means "blocks may not diverge from me". Health has none of that.
There is no block-side row to copy into and nothing to reconcile, because a
block's definition is resolved at read time from three tiers:

    PLATFORM_DEFAULT_DEFINITION
      <- public.crop_health_definitions, merged along the crop path
        <- farms.health_definition                     (this column)

Shallow merge, deepest tier winning per key, exactly the rule
`farms/crop_thresholds.resolve_thresholds` already uses. So there is no
Apply endpoint and no apply-preview, and adding one later would be a
mistake: it would copy a resolved answer into blocks and immediately start
drifting from the tiers it was resolved from. That is the failure this whole
project exists to end — three copies of one rule, two of which disagreed in
production.

**`health_definition` is a PARTIAL body, and NULL means no override.** A
farm names only what it wants to differ and inherits the rest, the same way
a crop does. Storing a resolved definition would freeze whatever the crop
and platform happened to say on the day it was saved, and the farm would
stop tracking the knowledge base without anyone being told.

**What `health_locked` means here is different from the other categories.**
Elsewhere the lock stops BLOCKS diverging from the farm. There are no blocks
to diverge, so here it stops the farm's own override being edited: a tenant
admin pins the definition and `PUT .../config/health/template` refuses until
it is unlocked. Locking needs no divergence check and no "lock and
overwrite" modal, because nothing can be out of step — the diff is
trivially empty and the service returns it as matched.

No CHECK can express the definition schema. `parse_definition` is the gate,
run before the write in `farms/config_template.replace_health_template`,
and it refuses an unknown key rather than letting it mean the default for
ever. The CHECK here only pins the JSON shape.

Revision ID: 0090
Revises: 0089
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0090"
down_revision: str | Sequence[str] | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column("health_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column(
            "health_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    # An override that is present but not an object would reach
    # `parse_definition` as a list or a string and raise on every read of
    # every block on the farm. NULL is the "no override" case and is allowed
    # explicitly: `jsonb_typeof(NULL)` is NULL, and NULL is not TRUE, so the
    # type test alone would reject exactly the normal case.
    #
    # The name here is the SUFFIX only. It fills the convention's
    # `%(constraint_name)s` slot and renders as
    # `ck_farms_health_definition_is_object`. Passing the full name doubles
    # the prefix, and the downgrade then cannot drop what it created. That
    # is not hypothetical: every CHECK on `blocks` is live on prod as
    # `ck_blocks_ck_blocks_unit_type` and friends, and so are
    # `platform_alerts`'.
    op.create_check_constraint(
        "health_definition_is_object",
        "farms",
        "health_definition IS NULL OR jsonb_typeof(health_definition) = 'object'",
    )


def downgrade() -> None:
    # The SUFFIX again, for the same reason the create passes one:
    # `drop_constraint` runs the name through the same naming convention, so
    # a full name here becomes `ck_farms_ck_farms_health_definition_is_object`
    # and the drop fails on a constraint that was never created. Every test
    # that downgrades a tenant schema past this point hits it.
    op.drop_constraint("health_definition_is_object", "farms", type_="check")
    op.drop_column("farms", "health_locked")
    op.drop_column("farms", "health_definition")
