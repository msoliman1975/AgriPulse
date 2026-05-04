"""Per-tenant imagery subscriptions, ingestion jobs, indices hypertable.

Per data_model § 6.4 / § 6.5 / § 7.3 / § 14. All tables live in the
per-tenant schema; the migration is applied once per tenant by the
runner in scripts/migrate_tenants.py (and on tenant creation by
tenancy.bootstrap).

Five things land here:

  1. `imagery_aoi_subscriptions` — which products are ingested for which
     blocks. The "what to fetch" registry. ON DELETE CASCADE from blocks
     so soft-archiving a block also disables its subscriptions.

  2. `imagery_ingestion_jobs` — one row per (subscription, scene)
     pipeline run. UNIQUE(subscription_id, scene_id) is the idempotency
     key — re-discovering the same scene is a no-op.

  3. `block_index_aggregates` — TimescaleDB hypertable, one row per
     (block, scene_time, index, product). UNIQUE(time, block_id,
     index_code, product_id) is the per-scene idempotency key. The
     `valid_pixel_pct` column is GENERATED ALWAYS (TimescaleDB ≥ 2.11
     supports stored generated columns on non-time / non-space columns).

  4. `block_index_daily` and `block_index_weekly` continuous aggregates
     per § 14.1, with refresh policies.

  5. RLS policy on `pgstac.items` keyed on the tenant_collection_prefix
     GUC set by `app.shared.db.session._set_search_path`. pgstac itself
     is tenancy-unaware; the policy is the second line of defense after
     the `collection LIKE 'tenant_<id>__%'` filter the application adds
     to every query.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _current_schema() -> str:
    """Return the tenant schema name this migration is running against.

    The tenant alembic env pins `search_path = <schema>, public` before
    `run_migrations`. Reading `current_schema()` is therefore the most
    reliable way to grab the tenant schema without re-parsing -x args.
    """
    bind = op.get_bind()
    return str(bind.execute(sa.text("SELECT current_schema()")).scalar())


def upgrade() -> None:
    schema = _current_schema()

    # ---- imagery_aoi_subscriptions -------------------------------------
    op.create_table(
        "imagery_aoi_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Logical cross-schema FK to public.imagery_products.id. The
        # consistency-check job from Slice 1 PR-D inspects these
        # relationships periodically; the FK itself is application-
        # enforced (see ARCHITECTURE.md § 5).
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Both nullable: NULL means "use tenant default" per the column
        # comment in data_model § 6.4. Q3 in the PR-A plan.
        sa.Column("cadence_hours", sa.Integer(), nullable=True),
        sa.Column("cloud_cover_max_pct", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("last_successful_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name="fk_imagery_aoi_subscriptions_block_id_blocks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cadence_hours IS NULL OR cadence_hours > 0",
            name="ck_imagery_aoi_subscriptions_cadence_positive",
        ),
        sa.CheckConstraint(
            "cloud_cover_max_pct IS NULL OR (cloud_cover_max_pct BETWEEN 0 AND 100)",
            name="ck_imagery_aoi_subscriptions_cloud_cover_range",
        ),
    )
    op.create_index(
        "uq_imagery_aoi_subscriptions_block_product_active",
        "imagery_aoi_subscriptions",
        ["block_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.create_index(
        "ix_imagery_aoi_subscriptions_last_attempted",
        "imagery_aoi_subscriptions",
        ["last_attempted_at"],
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.execute(
        "CREATE TRIGGER trg_imagery_aoi_subscriptions_updated_at "
        "BEFORE UPDATE ON imagery_aoi_subscriptions "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- imagery_ingestion_jobs ----------------------------------------
    op.create_table(
        "imagery_ingestion_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("scene_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("cloud_cover_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("valid_pixel_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stac_item_id", sa.Text(), nullable=True),
        sa.Column(
            "assets_written",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["imagery_aoi_subscriptions.id"],
            # Postgres caps identifiers at 63 chars; the convention name
            # `fk_imagery_ingestion_jobs_subscription_id_imagery_aoi_subscriptions`
            # is 67 chars. Use the short form for both schema and ORM.
            name="fk_imagery_ingestion_jobs_subscription_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending','running','succeeded','failed',"
            "'skipped_cloud','skipped_duplicate'"
            ")",
            name="ck_imagery_ingestion_jobs_status",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "scene_id",
            name="uq_imagery_ingestion_jobs_subscription_id_scene_id",
        ),
    )
    op.create_index(
        "ix_imagery_ingestion_jobs_block_scene_datetime",
        "imagery_ingestion_jobs",
        ["block_id", sa.text("scene_datetime DESC")],
    )
    op.create_index(
        "ix_imagery_ingestion_jobs_status_requested",
        "imagery_ingestion_jobs",
        ["status", "requested_at"],
    )

    # ---- block_index_aggregates (hypertable) ---------------------------
    # No PK: TimescaleDB hypertables can't have a PK that excludes the
    # time partitioning column. The UNIQUE on (time, block_id, index_code,
    # product_id) is the per-scene idempotency key — re-running indices
    # computation is a no-op.
    op.create_table(
        "block_index_aggregates",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.Text(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mean", sa.Numeric(7, 4), nullable=True),
        sa.Column("min", sa.Numeric(7, 4), nullable=True),
        sa.Column("max", sa.Numeric(7, 4), nullable=True),
        sa.Column("p10", sa.Numeric(7, 4), nullable=True),
        sa.Column("p50", sa.Numeric(7, 4), nullable=True),
        sa.Column("p90", sa.Numeric(7, 4), nullable=True),
        sa.Column("std_dev", sa.Numeric(7, 4), nullable=True),
        sa.Column("valid_pixel_count", sa.Integer(), nullable=False),
        sa.Column("total_pixel_count", sa.Integer(), nullable=False),
        # Generated column (Postgres 12+, TimescaleDB ≥ 2.11 on non-time,
        # non-space columns). Per data_model § 7.3.
        sa.Column(
            "valid_pixel_pct",
            sa.Numeric(5, 2),
            sa.Computed(
                "100.0 * valid_pixel_count / NULLIF(total_pixel_count, 0)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("cloud_cover_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("stac_item_id", sa.Text(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "time",
            "block_id",
            "index_code",
            "product_id",
            name="uq_block_index_aggregates_time_block_index_product",
        ),
        sa.CheckConstraint(
            "total_pixel_count >= 0 AND valid_pixel_count >= 0 "
            "AND valid_pixel_count <= total_pixel_count",
            name="ck_block_index_aggregates_pixel_counts",
        ),
    )

    # Convert to a TimescaleDB hypertable. Space partition by block_id
    # (4 partitions) per § 7.3. `create_hypertable` returns a row; the
    # `if_not_exists` guard makes the migration safe to re-run.
    op.execute(
        """
        SELECT create_hypertable(
            'block_index_aggregates',
            'time',
            partitioning_column => 'block_id',
            number_partitions => 4,
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )
    # Compression: enable after 30 days, segment by (block_id, index_code)
    # for selective decompression on dashboard queries.
    op.execute(
        """
        ALTER TABLE block_index_aggregates SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'block_id, index_code'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy("
        "'block_index_aggregates', INTERVAL '30 days', if_not_exists => TRUE)"
    )

    # No retention: § 7.3 keeps these aggregates indefinitely.

    op.create_index(
        "ix_block_index_aggregates_block_time_index",
        "block_index_aggregates",
        ["block_id", sa.text("time DESC"), "index_code"],
    )
    op.create_index(
        "ix_block_index_aggregates_index_time",
        "block_index_aggregates",
        ["index_code", sa.text("time DESC")],
    )
    op.create_index(
        "ix_block_index_aggregates_stac_item",
        "block_index_aggregates",
        ["stac_item_id"],
    )

    # ---- continuous aggregates ----------------------------------------
    # Daily mean per block per index — drives the trend chart. Refresh
    # hourly with a 2-day lookback so late-arriving data is captured.
    op.execute(
        """
        CREATE MATERIALIZED VIEW block_index_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', time) AS day,
            block_id,
            index_code,
            avg(mean) AS mean,
            min(min) AS min,
            max(max) AS max,
            sum(valid_pixel_count) AS valid_pixels,
            avg(valid_pixel_pct) AS valid_pct
        FROM block_index_aggregates
        GROUP BY day, block_id, index_code
        WITH NO DATA
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'block_index_daily',
            -- TimescaleDB requires (start - end) >= 2 buckets; a 2-day
            -- start with a 1-hour end falls just short for a 1-day
            -- bucket. Use 3 days so the policy covers 2+ daily buckets.
            start_offset => INTERVAL '3 days',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            if_not_exists => TRUE
        )
        """
    )

    # Weekly mean per block per index — used by the recommendation
    # evaluator (P4). Refresh daily with a 14-day lookback.
    op.execute(
        """
        CREATE MATERIALIZED VIEW block_index_weekly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('7 days', time) AS week,
            block_id,
            index_code,
            avg(mean) AS mean,
            stddev(mean) AS std_of_means
        FROM block_index_aggregates
        GROUP BY week, block_id, index_code
        WITH NO DATA
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'block_index_weekly',
            -- (start - end) must cover ≥ 2 weekly buckets.
            start_offset => INTERVAL '21 days',
            end_offset   => INTERVAL '1 day',
            schedule_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
        """
    )

    # ---- pgstac.items RLS policy ---------------------------------------
    # pgstac is tenancy-unaware. We enforce per-tenant isolation by:
    #   1. Always filtering by `collection LIKE 'tenant_<id>__%'` in
    #      application queries (PR-B/PR-C).
    #   2. This RLS policy as defense-in-depth, keyed on the
    #      `app.tenant_collection_prefix` GUC that
    #      `_set_search_path` sets per request.
    #
    # The policy name is per-tenant so multiple tenants' migrations can
    # coexist on the same shared `pgstac.items` table without colliding.
    policy_name = f"tenant_isolation_{schema}"
    op.execute("ALTER TABLE pgstac.items ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DROP POLICY IF EXISTS {policy_name} ON pgstac.items;
        CREATE POLICY {policy_name} ON pgstac.items
            FOR ALL
            USING (
                collection LIKE current_setting('app.tenant_collection_prefix', TRUE)
            )
            WITH CHECK (
                collection LIKE current_setting('app.tenant_collection_prefix', TRUE)
            )
        """
    )


def downgrade() -> None:
    schema = _current_schema()

    # Drop the per-tenant RLS policy. RLS itself stays enabled — other
    # tenants' policies still attach to it.
    policy_name = f"tenant_isolation_{schema}"
    op.execute(f"DROP POLICY IF EXISTS {policy_name} ON pgstac.items")

    # Continuous aggregates and their refresh policies.
    op.execute(
        "SELECT remove_continuous_aggregate_policy(" "'block_index_weekly', if_exists => TRUE)"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS block_index_weekly")
    op.execute(
        "SELECT remove_continuous_aggregate_policy(" "'block_index_daily', if_exists => TRUE)"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS block_index_daily")

    # Hypertable.
    op.execute("SELECT remove_compression_policy(" "'block_index_aggregates', if_exists => TRUE)")
    op.drop_index("ix_block_index_aggregates_stac_item", table_name="block_index_aggregates")
    op.drop_index("ix_block_index_aggregates_index_time", table_name="block_index_aggregates")
    op.drop_index(
        "ix_block_index_aggregates_block_time_index",
        table_name="block_index_aggregates",
    )
    op.drop_table("block_index_aggregates")

    # Ingestion jobs.
    op.drop_index(
        "ix_imagery_ingestion_jobs_status_requested",
        table_name="imagery_ingestion_jobs",
    )
    op.drop_index(
        "ix_imagery_ingestion_jobs_block_scene_datetime",
        table_name="imagery_ingestion_jobs",
    )
    op.drop_table("imagery_ingestion_jobs")

    # Subscriptions.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_imagery_aoi_subscriptions_updated_at "
        "ON imagery_aoi_subscriptions"
    )
    op.drop_index(
        "ix_imagery_aoi_subscriptions_last_attempted",
        table_name="imagery_aoi_subscriptions",
    )
    op.drop_index(
        "uq_imagery_aoi_subscriptions_block_product_active",
        table_name="imagery_aoi_subscriptions",
    )
    op.drop_table("imagery_aoi_subscriptions")
