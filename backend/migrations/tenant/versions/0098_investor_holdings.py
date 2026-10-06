"""Investor holdings — investors, holdings, and dated ownership.

A holding is a drawn polygon inside one block that an investor owns. The
company runs the farm; the investor only reads. Design:
docs/proposals/investor-holdings-design.html, sections 3 and 4.

Three tables:

* ``investors`` — the investor master. ``user_id`` is a logical pointer to
  ``public.users`` and has no FK, the rule for every tenant-to-public pointer.
  It stays NULL until the investor accepts an invite (a later stage).
* ``holdings`` — the polygon, its block, and its measured area. ``area_m2``
  is measured in the block's own UTM zone (``ST_SRID(blocks.boundary_utm)``),
  the same way the block's area is, so the share ``holding ÷ block`` compares
  two numbers measured with one ruler.
* ``holding_ownerships`` — who owned a holding between which dates. A harvest
  belongs to whoever owned the holding on the harvest date, so ownership is
  history, not a column on the holding.

Rules enforced here rather than only in the service, so no write path can
skip them:

* R1 — a holding lies inside its block, with 0.5 m of tolerance for a vertex
  drawn on the border.
* R2 — holdings in one block do not overlap. Hand-drawn neighbours share an
  edge and overlap by slivers, so an overlap under 1 m² is accepted.
* R6 — a block's boundary cannot change so that a live holding falls outside.
* R9 — ownership periods of one holding do not overlap (exclusion constraint).

The trigger errors carry fixed messages (``holding_outside_block``,
``holding_overlaps_holding``, ``block_boundary_cuts_holding``) that the
service maps to 409 / 422 responses.

``holdings.block_id`` is ``ON DELETE RESTRICT``: a block that people own part
of must not disappear by cascade. Purge deletes holdings first; see
``app/shared/purge/registry.py``.

Revision ID: 0098
Revises: 0097
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INVESTOR_TYPES = "'person', 'company'"
_INVESTOR_STATUSES = "'not_invited', 'invited', 'active', 'suspended', 'archived'"
_LANGUAGES = "'ar', 'en'"
_ID_TYPES = "'national_id', 'passport', 'commercial_register', 'other'"
_HOLDING_STATUSES = "'draft', 'available', 'archived'"
_ACQUIRED_BY = "'purchase', 'transfer', 'inheritance', 'other'"
_ENDED_BY = "'resale', 'buyback', 'contract_end', 'correction', 'other'"


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("uuid_generate_v7()"),
    )


def upgrade() -> None:
    # Already installed by 0054 on every tenant that reached it; repeated so
    # this migration does not depend on that history.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # -- investors --------------------------------------------------------
    op.create_table(
        "investors",
        _uuid_pk(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("investor_type", sa.Text(), nullable=False, server_default=sa.text("'person'")),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("full_name_ar", sa.Text(), nullable=True),
        sa.Column("contact_person", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        # Only the last 4 characters. The full document stays in the company's
        # contract files; this is for identity checks on a support call.
        sa.Column("national_id_type", sa.Text(), nullable=True),
        sa.Column("national_id_last4", sa.Text(), nullable=True),
        sa.Column("nationality", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("preferred_language", sa.Text(), nullable=False, server_default=sa.text("'ar'")),
        # Logical reference to public.users. No FK across schemas.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'not_invited'")),
        # Logical reference to public.users: the staff member who handles
        # this investor.
        sa.Column("relationship_manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes_internal", sa.Text(), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_app_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        # `name=` fills the convention's %(constraint_name)s slot; passing the
        # full name doubles the prefix and the downgrade cannot drop it.
        sa.CheckConstraint(f"investor_type IN ({_INVESTOR_TYPES})", name="investor_type"),
        sa.CheckConstraint(f"status IN ({_INVESTOR_STATUSES})", name="status"),
        sa.CheckConstraint(f"preferred_language IN ({_LANGUAGES})", name="language"),
        sa.CheckConstraint(
            f"national_id_type IS NULL OR national_id_type IN ({_ID_TYPES})",
            name="id_type",
        ),
        sa.CheckConstraint(
            "national_id_last4 IS NULL OR char_length(national_id_last4) <= 4",
            name="id_last4_len",
        ),
    )
    op.create_index(
        "uq_investors_code_live",
        "investors",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_investors_email_live ON investors (lower(email)) "
        "WHERE deleted_at IS NULL"
    )
    op.create_index(
        "ix_investors_user_id",
        "investors",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # -- holdings ---------------------------------------------------------
    op.create_table(
        "holdings",
        _uuid_pk(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column(
            "boundary",
            Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Numeric(14, 2), nullable=False),
        sa.Column("tree_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("notes_internal", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(f"status IN ({_HOLDING_STATUSES})", name="status"),
        sa.CheckConstraint("tree_count IS NULL OR tree_count >= 0", name="tree_count"),
        sa.CheckConstraint("area_m2 > 0", name="area_positive"),
    )
    op.create_index(
        "uq_holdings_code_live",
        "holdings",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_holdings_block_live",
        "holdings",
        ["block_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute("CREATE INDEX ix_holdings_boundary ON holdings USING gist (boundary)")

    # R1 + R2, and the area stamp. One BEFORE trigger so the three see the
    # same row. Archived holdings are exempt from R2: an archived holding
    # sold nothing, and its land can be drawn again.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION holdings_check_geometry() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_block_utm geometry;
          v_srid integer;
          v_utm geometry;
          v_overlap double precision;
        BEGIN
          IF NEW.deleted_at IS NOT NULL THEN
            RETURN NEW;
          END IF;

          SELECT b.boundary_utm INTO v_block_utm
            FROM blocks b
           WHERE b.id = NEW.block_id AND b.deleted_at IS NULL;
          IF v_block_utm IS NULL THEN
            RAISE EXCEPTION 'holding_block_missing' USING ERRCODE = 'P0001';
          END IF;

          v_srid := ST_SRID(v_block_utm);
          v_utm := ST_Transform(NEW.boundary, v_srid);
          NEW.area_m2 := round(ST_Area(v_utm)::numeric, 2);

          IF NOT ST_CoveredBy(v_utm, ST_Buffer(v_block_utm, 0.5)) THEN
            RAISE EXCEPTION 'holding_outside_block' USING ERRCODE = 'P0001';
          END IF;

          IF NEW.archived_at IS NULL THEN
            SELECT max(ST_Area(ST_Intersection(v_utm, ST_Transform(o.boundary, v_srid))))
              INTO v_overlap
              FROM holdings o
             WHERE o.block_id = NEW.block_id
               AND o.id <> NEW.id
               AND o.deleted_at IS NULL
               AND o.archived_at IS NULL
               AND o.boundary && NEW.boundary;
            IF coalesce(v_overlap, 0) > 1.0 THEN
              RAISE EXCEPTION 'holding_overlaps_holding' USING ERRCODE = 'P0001';
            END IF;
          END IF;

          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_holdings_check_geometry
        BEFORE INSERT OR UPDATE OF boundary, block_id, archived_at, deleted_at ON holdings
        FOR EACH ROW EXECUTE FUNCTION holdings_check_geometry();
        """
    )

    # R6 — the block side of R1. Without it a block redraw leaves a sold
    # holding hanging over the border with no error.
    #
    # Postgres fires BEFORE triggers in name order. This one must run after
    # trg_blocks_geom_compute has recomputed NEW.boundary_utm, so its name
    # sorts after "geom" ("holdings" > "geom"). Renaming it breaks R6.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION blocks_check_holdings_inside() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM holdings h
             WHERE h.block_id = NEW.id
               AND h.deleted_at IS NULL
               AND h.archived_at IS NULL
               AND NOT ST_CoveredBy(
                     ST_Transform(h.boundary, ST_SRID(NEW.boundary_utm)),
                     ST_Buffer(NEW.boundary_utm, 0.5))
          ) THEN
            RAISE EXCEPTION 'block_boundary_cuts_holding' USING ERRCODE = 'P0001';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_blocks_holdings_inside
        BEFORE UPDATE OF boundary ON blocks
        FOR EACH ROW EXECUTE FUNCTION blocks_check_holdings_inside();
        """
    )

    # -- holding_ownerships ----------------------------------------------
    op.create_table(
        "holding_ownerships",
        _uuid_pk(),
        sa.Column(
            "holding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("holdings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "investor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        # Last day of ownership, inclusive. NULL = still owns.
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("acquired_by", sa.Text(), nullable=False, server_default=sa.text("'purchase'")),
        sa.Column("ended_by", sa.Text(), nullable=True),
        sa.Column("contract_ref", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(f"acquired_by IN ({_ACQUIRED_BY})", name="acquired_by"),
        sa.CheckConstraint(f"ended_by IS NULL OR ended_by IN ({_ENDED_BY})", name="ended_by"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="date_order"),
    )
    # R9. '[]' because end_date is the last day owned, inclusive.
    op.execute(
        """
        ALTER TABLE holding_ownerships
          ADD CONSTRAINT ex_holding_ownerships_no_overlap
          EXCLUDE USING gist (
            holding_id WITH =,
            daterange(start_date, end_date, '[]') WITH &&
          ) WHERE (deleted_at IS NULL)
        """
    )
    op.create_index(
        "ix_holding_ownerships_investor",
        "holding_ownerships",
        ["investor_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    for table in ("investors", "holdings", "holding_ownerships"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
            """
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_blocks_holdings_inside ON blocks")
    op.execute("DROP FUNCTION IF EXISTS blocks_check_holdings_inside()")
    op.drop_table("holding_ownerships")
    op.execute("DROP TRIGGER IF EXISTS trg_holdings_check_geometry ON holdings")
    op.drop_table("holdings")
    op.execute("DROP FUNCTION IF EXISTS holdings_check_geometry()")
    op.drop_table("investors")
    # btree_gist stays installed; 0054 depends on it.
