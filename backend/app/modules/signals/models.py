"""Signals ORM models. Catalog in `public`, operational data per tenant.

The catalog gained a platform tier (public migration 0052 / tenant 0063):
`signal_definitions`, `signal_templates` and `signal_template_definitions`
moved to `public` with a nullable `tenant_id` acting as the scope
discriminator, mirroring `public.decision_trees`::

    tenant_id IS NULL      -> platform-curated  (authored at /platform/signals)
    tenant_id IS NOT NULL  -> tenant-authored

Reads must therefore be two-tier — `WHERE tenant_id IS NULL OR tenant_id = :tid`
— and where two rows share a `code`, **the tenant's row shadows the platform
one** (see `snapshot.py`). Writes must stamp `tenant_id` and must refuse to
touch platform rows from a tenant context.

`signal_assignments` and `signal_observations` stay per-tenant: they are
operational data, not catalog. `signal_assignments.signal_definition_id` is now
a cross-schema FK into `public.signal_definitions`, the same shape as
`tenant_memberships.user_id -> public.users.id`. `signal_observations`
references definitions with **no FK at all** — a deliberate logical reference,
which is why the migration preserved primary keys and the hypertable never had
to be rewritten.

`signal_observations` is a TimescaleDB hypertable (no `PRIMARY KEY`
that excludes the time column); we expose `time` + `id` as the replay
unique key. Application-level UUID v7 keeps inserts ordered.

Custom Signals (CS-1) additions:
- `observed_at` / `recorded_at` SQLAlchemy synonyms over the existing
  `time` / `inserted_at` columns. New code uses the synonym; the
  underlying DB columns stay unchanged. The hypertable partition key
  rename was deferred (see migrations/tenant/versions/0029_*.py).
- `location_mode` + `location_point` on observations (D2). The
  ST_Within trigger that enforces `point_in_entity` lives in the
  migration; access through the repository as PostGIS rendering.
- `aggregation` + `aggregation_window_days` on definitions (D3).
- `template_observation_id` self-ref on observations (D8).
- `SignalTemplate` + `SignalTemplateDefinition` for the
  group-N-defs-for-UX pattern (D1).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class SignalDefinition(Base, TimestampedMixin):
    """`public.signal_definitions` — what kinds of signals exist.

    Two-tier: ``tenant_id IS NULL`` is a platform-curated definition visible to
    every tenant; a non-NULL ``tenant_id`` is that tenant's own. Code uniqueness
    is partitioned by scope via two partial indexes, both of which keep the
    original ``deleted_at IS NULL`` predicate so a soft-deleted definition frees
    its code for reuse.
    """

    __tablename__ = "signal_definitions"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    # NULL = platform-curated. No FK to public.tenants: purge removes tenant
    # rows through the ownership manifest (shared/purge/registry.py), and a
    # CASCADE here would let a tenant delete take the platform catalog with it.
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Arabic display name (public migration 0075). Nullable; readers fall
    # back with COALESCE(NULLIF(name_ar, ''), name).
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_kind: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorical_values: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # Parallel to `categorical_values`: same length, same order, one Arabic
    # label per code. A CHECK in migration 0075 enforces the equal length,
    # because a shorter array would render a blank option, not an error.
    categorical_values_ar: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    value_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    value_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    attachment_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    # CS-1 D3 / CS-14: per-definition aggregation rule ∈ {latest, mean,
    # median, max, min, sum, count}. The recommendations engine uses
    # `aggregation` + `aggregation_window_days` to collapse multiple
    # observations to a single block-level value. `count` works for any
    # value_kind (counts observations); every other non-`latest` rule is
    # numeric-only and non-numeric kinds coerce to `latest` — validated at
    # the schema layer (CHECK only pins the allowed string values).
    aggregation: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'latest'"))
    aggregation_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SignalAssignment(Base, TimestampedMixin):
    """`tenant_<id>.signal_assignments` — which farms/blocks a definition applies to.

    A row with both `farm_id` and `block_id` NULL means tenant-wide.
    """

    __tablename__ = "signal_assignments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    # Deliberately NOT a foreign key into public.signal_definitions, even
    # though the row does reference it. A tenant -> public FK makes the
    # referenced table part of every tenant schema's dependency graph, so
    # `DROP SCHEMA tenant_x CASCADE` must take an ACCESS EXCLUSIVE lock on
    # public.signal_definitions to drop the constraint. That lock conflicts
    # with the ROW EXCLUSIVE any other tenant holds while creating a tenant or
    # authoring a signal, so a single purge serialises tenant lifecycle across
    # the whole platform — and blocks indefinitely behind one idle transaction.
    # Found exactly that way: nine tenancy tests went from 9s to a hard hang.
    #
    # Nothing is lost. The FK's ON DELETE CASCADE could never fire: definitions
    # are soft-deleted (`deleted_at`), and the one hard delete — tenant purge —
    # removes signal_assignments through its own manifest entry, whose `fk`
    # flag is informational because the engine always deletes explicitly.
    #
    # This is also the only shape the rest of the schema uses: no other tenant
    # table carries an FK into public. (An earlier comment here claimed
    # tenant_memberships.user_id as precedent; that table lives in *public*,
    # so its FK is public -> public and proves the opposite.)
    signal_definition_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    farm_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    block_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class SignalObservation(Base):
    """`tenant_<id>.signal_observations` — TimescaleDB hypertable.

    No PK on a single column: TimescaleDB requires the partition column
    in any unique constraint. We declare `(time, id)` as the replay
    UNIQUE; UUID v7 ids generated by the service layer keep inserts
    monotonic for the time-id pair.
    """

    __tablename__ = "signal_observations"
    __table_args__: tuple[UniqueConstraint | dict[str, object], ...] = (
        UniqueConstraint("time", "id", name="uq_signal_observations_time_id"),
        {},
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, server_default=UUID_V7_DEFAULT, primary_key=True
    )
    signal_definition_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    block_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    farm_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_categorical: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_event: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # value_geopoint stored as PostGIS geometry(Point,4326); not exposed via ORM
    # (consumers go through the repository which renders GeoJSON).
    # location_point follows the same pattern — see CS-1 migration 0029.
    attachment_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # CS-1 D2: how the observation is geolocated.
    #   entity           → the observation refers to the whole block/farm;
    #                      location_point is NULL.
    #   point_in_entity  → location_point is a precise lat/lon that must
    #                      lie within the referenced block (ST_Within
    #                      trigger enforces this in DB).
    #   free_point       → location_point is anywhere on earth; block_id
    #                      may be NULL.
    location_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'entity'")
    )

    # CS-1 D8: self-reference for template-grouped observations. The
    # lead row of a template-group stores its own id; siblings carry
    # the lead row's id. NULL = standalone observation. Application-
    # enforced (no FK — see migration for rationale).
    template_observation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    # CS-7 batch undo: the CSV upload that created this row. NULL for
    # single-shot / template observations recorded outside a CSV import.
    # One fresh UUID per upload, assigned by the service layer. Backed by
    # a partial index (migration 0038) for the list / delete-by-batch
    # lookups.
    import_batch_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # CS-1 D7 (synonym path — full rename deferred): new code can read
    # / write `observed_at` and `recorded_at`. The underlying DB
    # columns (`time`, `inserted_at`) are unchanged so the TimescaleDB
    # hypertable partition stays valid. When CS-1b ships the real
    # rename, drop these synonyms and rename the columns.
    observed_at = synonym("time")
    recorded_at = synonym("inserted_at")


class SignalTemplate(Base, TimestampedMixin):
    """`public.signal_templates` — CS-1 D1.

    Groups N `SignalDefinition`s for the entry/log UX. The engine
    still sees flat per-definition observations; templates are a
    UX-only construct. Codes are unique among live rows, partitioned
    by scope like `SignalDefinition`.
    """

    __tablename__ = "signal_templates"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    # NULL = platform-curated; see SignalDefinition.tenant_id.
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # See SignalDefinition.name_ar (public migration 0075).
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class SignalTemplateDefinition(Base):
    """`public.signal_template_definitions` — junction table.

    Ordered (`position`) and optionally `is_required`. The
    per-template UX uses `position` for field order and `is_required`
    to mark fields the operator must fill before submitting the
    grouped log. The underlying per-definition observations are always
    nullable — required-ness is a UX hint only.
    """

    __tablename__ = "signal_template_definitions"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    # Owned transitively through its template — the junction carries no
    # tenant_id of its own, so it never appears in the purge ownership sweep.
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.signal_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_definition_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.signal_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
