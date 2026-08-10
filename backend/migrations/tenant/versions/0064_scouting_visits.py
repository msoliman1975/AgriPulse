"""Scouting visits + routing rules — the dispatch half of the scout app (S1).

A *visit* is the unit of scouting work: someone is asked to stand in a
particular block (or grid cell) before a deadline and record what they see.
Observations themselves are not stored here — they stay in
``signal_observations``, so the decision-tree feedback path is untouched. This
table carries only what signals cannot express: who was asked, why, by when,
and how it ended.

Five origins, because where a visit comes from changes the copy, the deadline
and the surface it renders on, but not its structure:

``recommendation``  a tree emitted ``action_type: scout`` (deadline from the
                    leaf's ``parameters.within_hours``)
``alert``           an alert opened above a severity floor
``routine``         a scheduled round
``ad_hoc``          **a supervisor saw something on the map** — the only origin
                    carrying human instructions and a dropped pin
``self_initiated``  the scout was already there; created in ``in_progress``

Routing rules decide whether a machine-created visit lands in a supervisor's
queue (``triage``) or is assigned immediately (``auto``), resolved
most-specific-first: block → farm → tenant-wide. A rule in ``auto`` mode with
no resolvable assignee is expected to degrade to ``triage`` in the service
layer rather than drop the visit; silent loss is the worst outcome available.

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2.types import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINS = "'recommendation', 'alert', 'routine', 'ad_hoc', 'self_initiated'"
# `expired` is a flag, not a closure: the sweep sets it, escalates, and the
# visit stays actionable. Auto-closing overdue work would make a neglected farm
# look identical to a healthy one.
_STATUSES = (
    "'queued', 'assigned', 'accepted', 'in_progress', "
    "'completed', 'declined', 'cancelled', 'expired'"
)
# "I went and could not tell" is the most common real result of a field visit;
# forcing it into resolved/unresolved manufactures false data.
_OUTCOMES = "'resolved', 'inconclusive', 'blocked'"
_SEVERITIES = "'info', 'warning', 'critical'"
_PRIORITIES = "'low', 'medium', 'high'"


def upgrade() -> None:
    op.create_table(
        "scouting_visits",
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
        # Sub-block grid cell. Recommendations already carry cell_id, and
        # sending someone to a 40-hectare block when the anomaly sits in one
        # cell wastes the visit. No FK: grid cells are rebuilt on rezone.
        sa.Column("cell_id", postgresql.UUID(as_uuid=True), nullable=True),
        # --- provenance ------------------------------------------------------
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        # The supervisor's own words — ad_hoc only. Every other origin renders
        # its text from a template, which is why this one gets its own surface
        # treatment in the app.
        sa.Column("instruction", sa.Text(), nullable=True),
        # Tree text, severity and the index values as they stood when the visit
        # was raised. Snapshotted so the reason cannot drift or vanish
        # underneath a scout who is standing in the field reading it.
        sa.Column("reason_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "pin_point",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        # --- urgency ---------------------------------------------------------
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("priority", sa.Text(), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        # --- lifecycle -------------------------------------------------------
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        # NULL while assigned_to is set means a routing rule did it, not a
        # human — which is exactly the distinction a supervisor board needs.
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        # --- capture ----------------------------------------------------------
        # Which platform/tenant form to present, and the lead row of the
        # resulting signal_observations group (its template_observation_id).
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary_note", sa.Text(), nullable=True),
        # Client-generated (UUID v7). The submit call is a single batch, and a
        # scout on a bad connection will retry it.
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"origin IN ({_ORIGINS})", name="origin"),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="status"),
        sa.CheckConstraint(f"outcome IS NULL OR outcome IN ({_OUTCOMES})", name="outcome"),
        sa.CheckConstraint(f"severity IN ({_SEVERITIES})", name="severity"),
        sa.CheckConstraint(f"priority IN ({_PRIORITIES})", name="priority"),
        # A completed visit must say how it ended, and only a completed visit
        # may. Without this, "done" and "done, cause unknown" collapse into one.
        sa.CheckConstraint(
            "(status = 'completed') = (outcome IS NOT NULL)",
            name="outcome_iff_completed",
        ),
        # Declining is legitimate; declining silently is not.
        sa.CheckConstraint(
            "status <> 'declined' OR decline_reason IS NOT NULL",
            name="decline_needs_reason",
        ),
        # Only a supervisor's ad-hoc dispatch carries instructions or a pin.
        sa.CheckConstraint(
            "origin = 'ad_hoc' OR (instruction IS NULL AND pin_point IS NULL)",
            name="instruction_is_ad_hoc_only",
        ),
    )

    # The daily evaluator re-walks every tree, so a persistent NDVI dip would
    # queue a brand-new visit every morning without this. Cancelled/expired
    # rows are excluded so a block can legitimately be re-scouted later.
    op.create_index(
        "uq_scouting_visits_live_recommendation",
        "scouting_visits",
        ["recommendation_id"],
        unique=True,
        postgresql_where=sa.text(
            "recommendation_id IS NOT NULL AND status NOT IN ('cancelled', 'expired')"
        ),
    )
    op.create_index(
        "uq_scouting_visits_idempotency_key",
        "scouting_visits",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    # The overdue sweep and the supervisor board.
    op.create_index("ix_scouting_visits_status_due", "scouting_visits", ["status", "due_by"])
    # "My visits" on the phone.
    op.create_index("ix_scouting_visits_assignee", "scouting_visits", ["assigned_to", "status"])
    op.create_index(
        "ix_scouting_visits_farm_status", "scouting_visits", ["farm_id", "status", "due_by"]
    )
    op.create_index("ix_scouting_visits_block", "scouting_visits", ["block_id"])

    op.execute(
        "CREATE TRIGGER trg_scouting_visits_updated_at "
        "BEFORE UPDATE ON scouting_visits "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- routing rules -----------------------------------------------------
    op.create_table(
        "scouting_routing_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # Both NULL = the tenant-wide default. Resolution is
        # most-specific-first: block → farm → tenant.
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # NULL = applies to any origin / any severity.
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("min_severity", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False, server_default=sa.text("'triage'")),
        sa.Column("default_assignee", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fallback_assignee", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Used when the origin carries no within_hours of its own.
        sa.Column("default_due_hours", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('triage', 'auto')", name="mode"),
        sa.CheckConstraint(f"origin IS NULL OR origin IN ({_ORIGINS})", name="origin"),
        sa.CheckConstraint(
            f"min_severity IS NULL OR min_severity IN ({_SEVERITIES})", name="min_severity"
        ),
        sa.CheckConstraint(
            "default_due_hours IS NULL OR default_due_hours > 0", name="due_hours_positive"
        ),
        # A block-scoped rule must name its farm, so resolution never has a
        # hole in the middle of the block → farm → tenant walk.
        sa.CheckConstraint("block_id IS NULL OR farm_id IS NOT NULL", name="block_implies_farm"),
    )
    op.create_index(
        "uq_scouting_routing_rules_scope",
        "scouting_routing_rules",
        ["farm_id", "block_id", "origin"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_scouting_routing_rules_updated_at "
        "BEFORE UPDATE ON scouting_routing_rules "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_scouting_routing_rules_updated_at ON scouting_routing_rules"
    )
    op.drop_index("uq_scouting_routing_rules_scope", table_name="scouting_routing_rules")
    op.drop_table("scouting_routing_rules")

    op.execute("DROP TRIGGER IF EXISTS trg_scouting_visits_updated_at ON scouting_visits")
    for idx in (
        "ix_scouting_visits_block",
        "ix_scouting_visits_farm_status",
        "ix_scouting_visits_assignee",
        "ix_scouting_visits_status_due",
        "uq_scouting_visits_idempotency_key",
        "uq_scouting_visits_live_recommendation",
    ):
        op.drop_index(idx, table_name="scouting_visits")
    op.drop_table("scouting_visits")
