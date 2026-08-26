"""Plan-template catalog ORM models (public schema).

Platform-curated agriculture plan templates keyed by a crop-taxonomy
``crop_path``. A template is a header + template-local milestones +
activities; activities anchor to ``start``, a milestone, or a phenology
``stage`` (the spine — resolved per block at apply time). Tenants apply a
template to a farm's matching-crop blocks, materialising the existing
``vegetation_plans`` / ``plan_activities`` rows. See
``docs/proposals/phenology-spine-and-stage-aware-planning.md`` §1.4/§4.
"""

from __future__ import annotations

from datetime import time
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class PlanTemplate(Base, TimestampedMixin):
    """`public.plan_templates` — platform-curated; tenants apply read-only."""

    __tablename__ = "plan_templates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_plan_templates_status",
        ),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Arabic display name (public migration 0074). Nullable; readers fall
    # back with COALESCE(NULLIF(name_ar, ''), name).
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Crop-taxonomy targeting key, prefix-matched against block_crops.crop_path
    # (e.g. ``mango`` / ``mango.alphonso`` / ``mango.alphonso.short``).
    crop_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalised from the path's first segment for display + crop-scoped reads.
    crop_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))


class PlanTemplateMilestone(Base, TimestampedMixin):
    """`public.plan_template_milestones` — template-local named days."""

    __tablename__ = "plan_template_milestones"
    __table_args__ = (
        UniqueConstraint("template_id", "code", name="uq_plan_template_milestone_code"),
        CheckConstraint("day_from_start >= 0", name="ck_plan_template_milestone_day"),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.plan_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # See PlanTemplate.name_ar (public migration 0074).
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    day_from_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class PlanTemplateActivity(Base, TimestampedMixin):
    """`public.plan_template_activities` — typed activities with an anchor.

    ``anchor`` ∈ start | milestone | stage:
      * ``start``     — offset from the per-block start date.
      * ``milestone`` — offset from a template-local milestone (``milestone_id``).
      * ``stage``     — offset from a phenology stage's resolved start date
        (``stage_code`` must exist in the template path's resolved stages).
    """

    __tablename__ = "plan_template_activities"
    __table_args__ = (
        CheckConstraint(
            "anchor IN ('start', 'milestone', 'stage')",
            name="ck_plan_template_activity_anchor",
        ),
        CheckConstraint(
            "(anchor <> 'milestone') OR (milestone_id IS NOT NULL)",
            name="ck_plan_template_activity_milestone_ref",
        ),
        CheckConstraint(
            "(anchor <> 'stage') OR (stage_code IS NOT NULL)",
            name="ck_plan_template_activity_stage_ref",
        ),
        CheckConstraint("duration_days >= 1", name="ck_plan_template_activity_duration"),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.plan_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    anchor: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'start'"))
    milestone_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.plan_template_milestones.id", ondelete="CASCADE"),
        nullable=True,
    )
    stage_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    dosage: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


__all__ = ["PlanTemplate", "PlanTemplateActivity", "PlanTemplateMilestone"]
