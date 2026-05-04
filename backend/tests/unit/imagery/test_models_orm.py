"""Unit tests for imagery ORM model shapes.

These don't touch a database — they assert the SQLAlchemy mapper
produced the right column set, schema placement, and constraints.
Schema-level invariants (hypertable creation, RLS, etc.) live in the
integration tests under tests/integration/imagery/.
"""

from __future__ import annotations

from app.modules.imagery.models import (
    ImageryAoiSubscription,
    ImageryIngestionJob,
    ImageryProduct,
    ImageryProvider,
)


def test_imagery_provider_lives_in_public_schema() -> None:
    assert ImageryProvider.__tablename__ == "imagery_providers"
    assert ImageryProvider.__table__.schema == "public"
    cols = {c.name for c in ImageryProvider.__table__.columns}
    assert {
        "id",
        "code",
        "name",
        "kind",
        "is_active",
        "config_schema",
        "created_at",
        "updated_at",
        "deleted_at",
    }.issubset(cols)


def test_imagery_product_lives_in_public_with_fk_to_provider() -> None:
    assert ImageryProduct.__tablename__ == "imagery_products"
    assert ImageryProduct.__table__.schema == "public"
    cols = {c.name for c in ImageryProduct.__table__.columns}
    assert {
        "id",
        "provider_id",
        "code",
        "name",
        "resolution_m",
        "revisit_days_avg",
        "bands",
        "supported_indices",
        "cost_tier",
        "is_active",
    }.issubset(cols)
    fks = {
        (fk.parent.name, fk.column.table.fullname) for fk in ImageryProduct.__table__.foreign_keys
    }
    assert ("provider_id", "public.imagery_providers") in fks


def test_imagery_aoi_subscription_lives_in_tenant_schema() -> None:
    """No `__table_args__["schema"]` — search_path resolves at query time."""
    assert ImageryAoiSubscription.__tablename__ == "imagery_aoi_subscriptions"
    assert ImageryAoiSubscription.__table__.schema is None
    cols = {c.name for c in ImageryAoiSubscription.__table__.columns}
    assert {
        "id",
        "block_id",
        "product_id",
        "cadence_hours",
        "cloud_cover_max_pct",
        "is_active",
        "last_successful_ingest_at",
        "last_attempted_at",
    }.issubset(cols)
    # cadence_hours and cloud_cover_max_pct are nullable per Q3 (NULL = use
    # tenant default).
    assert ImageryAoiSubscription.__table__.c.cadence_hours.nullable is True
    assert ImageryAoiSubscription.__table__.c.cloud_cover_max_pct.nullable is True


def test_imagery_aoi_subscription_cascades_from_blocks() -> None:
    fks = list(ImageryAoiSubscription.__table__.foreign_keys)
    block_fk = next(fk for fk in fks if fk.parent.name == "block_id")
    # SQLAlchemy stores ondelete as a SQL fragment string.
    assert block_fk.ondelete == "CASCADE"


def test_imagery_ingestion_job_columns() -> None:
    assert ImageryIngestionJob.__tablename__ == "imagery_ingestion_jobs"
    assert ImageryIngestionJob.__table__.schema is None
    cols = {c.name for c in ImageryIngestionJob.__table__.columns}
    assert {
        "id",
        "subscription_id",
        "block_id",
        "product_id",
        "scene_id",
        "scene_datetime",
        "requested_at",
        "started_at",
        "completed_at",
        "status",
        "cloud_cover_pct",
        "valid_pixel_pct",
        "error_message",
        "stac_item_id",
        "assets_written",
    }.issubset(cols)
    # No soft-delete on jobs — they're an append-mostly log.
    assert "deleted_at" not in cols


def test_imagery_ingestion_job_has_status_default_pending() -> None:
    status_col = ImageryIngestionJob.__table__.c.status
    assert status_col.server_default is not None
    assert "pending" in str(status_col.server_default.arg)
