"""Subscribe a FARM to a weather provider, not each of its blocks.

Weather has been farm-shaped all along and nobody moved the subscription to
match. The fetch takes one farm centroid and makes one provider call
(`fetch_weather(farm_id, provider_code)`), and `weather_observations` is keyed
on `(time, farm_id, provider_code, …)` — there is no per-block weather data
anywhere in the system. The per-block rows only decide *whether* the farm is
subscribed, carry a cadence, and spawn one identical attempt row per block.

On a 36-block farm that meant 36 attempt rows recording a single HTTP call.
The old comment called it "keeps each block's history independent even though
the provider call is shared" — but there is only one event, and writing it 36
times is not independence, it is duplication.

So:

* `weather_farm_subscriptions` — one row per (farm, provider), migrated from
  the block rows by taking the tightest cadence any block asked for, so no
  farm ends up polled less often than it was.
* `weather_ingestion_attempts.block_id` becomes nullable, and its FK to the
  block subscription is dropped. A farm-scoped attempt has no block, and the
  `subscription_id` can now point at either table — a logical reference, which
  is what it already is for everything that reads it. Health readers only ever
  pass `block_id` through; none group or filter on it.

The block rows are left in place and untouched. They are the rollback, and
nothing reads the new table until the weather tasks move over.

Revision ID: 0077
Revises: 0076
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

_ATTEMPT_FK = "fk_weather_ingestion_attempts_subscription_id"


def upgrade() -> None:
    op.create_table(
        "weather_farm_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column("cadence_hours", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("last_successful_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_weather_farm_subscriptions_active",
        "weather_farm_subscriptions",
        ["farm_id", "provider_code"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
    )

    # Collapse the per-block intent. min() on cadence for the same reason the
    # imagery collapse used it: a farm polled on the fastest cadence any of its
    # blocks wanted cannot leave a block staler than it was.
    op.execute(
        """
        INSERT INTO weather_farm_subscriptions (
            farm_id, provider_code, cadence_hours, is_active,
            last_successful_ingest_at, last_attempted_at
        )
        SELECT
            b.farm_id,
            s.provider_code,
            min(s.cadence_hours)              AS cadence_hours,
            TRUE                              AS is_active,
            max(s.last_successful_ingest_at)  AS last_successful_ingest_at,
            max(s.last_attempted_at)          AS last_attempted_at
        FROM weather_subscriptions s
        JOIN blocks b ON b.id = s.block_id
        WHERE s.is_active AND s.deleted_at IS NULL AND b.deleted_at IS NULL
        GROUP BY b.farm_id, s.provider_code
        """
    )

    # A farm-scoped attempt has no block, and subscription_id may now name a
    # row in either subscription table.
    op.drop_constraint(_ATTEMPT_FK, "weather_ingestion_attempts", type_="foreignkey")
    op.alter_column("weather_ingestion_attempts", "block_id", nullable=True)


def downgrade() -> None:
    # Farm-scoped attempts have no block to restore, so they cannot survive a
    # NOT NULL block_id. Drop them rather than invent an owner.
    op.execute("DELETE FROM weather_ingestion_attempts WHERE block_id IS NULL")
    op.alter_column("weather_ingestion_attempts", "block_id", nullable=False)
    op.create_foreign_key(
        _ATTEMPT_FK,
        "weather_ingestion_attempts",
        "weather_subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("uq_weather_farm_subscriptions_active", table_name="weather_farm_subscriptions")
    op.drop_table("weather_farm_subscriptions")
