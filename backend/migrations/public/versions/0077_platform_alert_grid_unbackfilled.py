"""Allow the `grid_unbackfilled` platform-alert kind.

`platform_alerts.kind` carries a CHECK against a fixed list, so a new
detector cannot write a row until the list is widened. Category is
unchanged: the alert is about index calculation output, which
`index_calc` already names.

The alert reports a farm whose sub-block grid holds no readings while the
farm has stored scenes. See `platform_alerts/detectors.py` for why that
state was invisible to every other detector.

Raw SQL rather than `op.drop_constraint` / `op.create_check_constraint`,
because the constraint's real name is not the name 0069 asked for. The
metadata naming convention (`ck_%(table_name)s_%(constraint_name)s`) is
applied at create time to a name that already carried the prefix, so the
live constraint is `ck_platform_alerts_ck_platform_alerts_kind` -- read
off production, not inferred. Both spellings are dropped IF EXISTS so this
applies cleanly whichever one a given database ended up with, and the new
one is added under a name written out in full.

Revision ID: 0077
Revises: 0076
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept as full literals rather than "the old list plus one" so the state
# after upgrade and after downgrade are both readable here, without
# opening 0069.
_KINDS_BEFORE = "'stream_silent', 'peer_lag', 'failure_streak', 'task_error', 'stuck_job'"
_KINDS_AFTER = (
    "'stream_silent', 'peer_lag', 'failure_streak', 'task_error', "
    "'stuck_job', 'grid_unbackfilled'"
)

_NAME = "ck_platform_alerts_ck_platform_alerts_kind"
_LEGACY_NAME = "ck_platform_alerts_kind"


def _replace_kind_check(kinds: str) -> None:
    for name in (_NAME, _LEGACY_NAME):
        op.execute(f"ALTER TABLE public.platform_alerts DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        f"ALTER TABLE public.platform_alerts " f"ADD CONSTRAINT {_NAME} CHECK (kind IN ({kinds}))"
    )


def upgrade() -> None:
    _replace_kind_check(_KINDS_AFTER)


def downgrade() -> None:
    # Rows of the new kind cannot survive the narrower constraint, and a
    # downgrade that aborts on live data is worse than one that drops the
    # observability rows it added. They are recomputed by the next sweep.
    op.execute("DELETE FROM public.platform_alerts WHERE kind = 'grid_unbackfilled'")
    _replace_kind_check(_KINDS_BEFORE)
