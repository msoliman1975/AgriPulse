"""Field flags — a scout reports something nobody asked about.

Every observation surface the platform has answers a question somebody already
posed: a visit was dispatched, a template was chosen, a signal was defined. A
scout who finds a cracked main line, a fallen tree, or a gate left open has
nowhere to put it, and today that finding lives in a phone call or nowhere.

A **field flag** is a note, some photographs, an optional position, a block,
and a severity the scout chose. It appears on the supervisor's map as a
coloured pin and carries a comment thread that a supervisor closes with a
reason. The closing reason is the whole point: it is how a scout learns
whether flagging was worth doing, which is what decides whether they keep
doing it.

Decisions worth stating, because each one has an obvious-looking alternative:

* **`block_id` is NOT NULL.** Flags aggregate per block alongside every other
  signal, and a second farm-shaped code path through the map layer and the
  panel would have to exist for the handful of findings that belong to no
  block. A gate or an access road is attached to the block it sits beside.
* **`pin_until` is stored on the row, not computed from the farm setting.**
  Reading it live would mean that editing one number removes hundreds of
  existing pins from the map, with nothing on screen connecting cause to
  effect.
* **Unpinned is not closed.** A flag whose pin has expired still appears in
  lists and may still have an open thread. Conflating the two is how open
  work disappears.
* **Re-opening resets `pin_until`.** A closed pin stays on the map for its
  full lifetime and a flag may be re-opened at any time — including after
  that lifetime ran out, which without this rule produces an open flag with
  no pin.
* **Closing requires a reason AND a comment**, enforced by a CHECK rather
  than by the service, so no future caller can close one silently.
* **No foreign keys into `public`.** `raised_by` / `closed_by` /
  `author_id` are logical references to `public.users.id`; a real FK would
  make `DROP SCHEMA tenant_x` take an ACCESS EXCLUSIVE lock platform-wide.

The farm-level setting lands on `farms` as `default_field_flag_pin_days`
alongside the existing `default_*` columns, with a `field_locked` companion
matching the grid / irrigation / org categories already there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The scout's three words map onto the vocabulary every other surface uses, so
# a flag sorts and colours beside an alert without a translation table.
_SEVERITIES = "'info', 'warning', 'critical'"
_STATUSES = "'open', 'closed'"
# Why it was closed. `no_action_needed` is a real answer and the one that tells
# a scout their judgement was heard and overruled; without it every close reads
# as "actioned" and the feedback is worthless.
_CLOSE_REASONS = "'actioned', 'no_action_needed', 'duplicate'"
# What a thread entry is. `close` and `reopen` are comments too — keeping them
# in one table means the thread reads in order without a union.
_COMMENT_KINDS = "'comment', 'close', 'reopen'"

_DEFAULT_PIN_DAYS = 14


def upgrade() -> None:
    op.create_table(
        "field_flags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # What the scout saw, in their words. The first line becomes the title
        # everywhere it is listed, the same trick ad-hoc visits use.
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        # Where the scout was standing, when they chose to say. Never enforced
        # to be inside the block: a GPS fix a few metres out is normal, and a
        # rejected write would lose work already done.
        sa.Column(
            "point",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("accuracy_m", sa.Integer(), nullable=True),
        # When the pin stops drawing. Set from the farm's setting at raise
        # time; reset when the flag is re-opened.
        sa.Column("pin_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raised_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(f"severity IN ({_SEVERITIES})", name="severity"),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="status"),
        sa.CheckConstraint(
            f"close_reason IS NULL OR close_reason IN ({_CLOSE_REASONS})",
            name="close_reason",
        ),
        # A closed flag says who closed it, when, and why — and an open one
        # says none of those. Enforced here so no caller can close silently.
        sa.CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL AND closed_by IS NOT NULL "
            "AND close_reason IS NOT NULL)",
            name="closed_iff_closure_recorded",
        ),
        sa.CheckConstraint("length(btrim(note)) > 0", name="note_not_blank"),
    )

    # The map asks one question: which flags does this farm still draw. Status
    # leads because "open only" is the checkbox supervisors will live in.
    op.create_index(
        "ix_field_flags_farm_status",
        "field_flags",
        ["farm_id", "status", "pin_until"],
    )
    op.create_index("ix_field_flags_block", "field_flags", ["block_id"])

    op.create_table(
        "field_flag_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "flag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_flags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'comment'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({_COMMENT_KINDS})", name="kind"),
        sa.CheckConstraint("length(btrim(body)) > 0", name="body_not_blank"),
    )
    op.create_index(
        "ix_field_flag_comments_flag",
        "field_flag_comments",
        ["flag_id", "created_at"],
    )

    op.create_table(
        "field_flag_photos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "flag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_flags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Object storage key, same bucket and the same presigned-PUT flow the
        # signals attachments use. Named so the purge registry can find and
        # delete the object when the farm or block goes.
        sa.Column("attachment_s3_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_field_flag_photos_flag", "field_flag_photos", ["flag_id"])

    # Farm-level setting, in the same shape as the grid / irrigation / org
    # categories already on this table: a `default_*` value plus a lock.
    op.add_column(
        "farms",
        sa.Column("default_field_flag_pin_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column(
            "field_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE farms SET default_field_flag_pin_days = :days "
            "WHERE default_field_flag_pin_days IS NULL"
        ).bindparams(days=_DEFAULT_PIN_DAYS)
    )


def downgrade() -> None:
    op.drop_column("farms", "field_locked")
    op.drop_column("farms", "default_field_flag_pin_days")
    op.drop_index("ix_field_flag_photos_flag", table_name="field_flag_photos")
    op.drop_table("field_flag_photos")
    op.drop_index("ix_field_flag_comments_flag", table_name="field_flag_comments")
    op.drop_table("field_flag_comments")
    op.drop_index("ix_field_flags_block", table_name="field_flags")
    op.drop_index("ix_field_flags_farm_status", table_name="field_flags")
    op.drop_table("field_flags")
