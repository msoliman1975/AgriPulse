"""Unit tests for imagery event payload shapes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.modules.imagery.events import (
    IndexAggregatedV1,
    IngestionFailedV1,
    SceneDiscoveredV1,
    SceneIngestedV1,
    SceneSkippedV1,
    SubscriptionCreatedV1,
    SubscriptionRevokedV1,
)


def test_subscription_created_serializes() -> None:
    ev = SubscriptionCreatedV1(
        subscription_id=uuid4(),
        block_id=uuid4(),
        product_id=uuid4(),
        actor_user_id=uuid4(),
    )
    payload = ev.model_dump(mode="json")
    assert ev.event_name == "imagery.subscription_created.v1"
    assert {"subscription_id", "block_id", "product_id", "actor_user_id"}.issubset(payload)


def test_subscription_revoked_event_name() -> None:
    ev = SubscriptionRevokedV1(subscription_id=uuid4(), block_id=uuid4())
    assert ev.event_name == "imagery.subscription_revoked.v1"


def test_scene_discovered_carries_cloud_cover() -> None:
    ev = SceneDiscoveredV1(
        job_id=uuid4(),
        subscription_id=uuid4(),
        block_id=uuid4(),
        scene_id="S2A_MSIL2A_20260501T084601_N0510_R107_T36RTU_20260501T112812",
        scene_datetime=datetime.now(UTC),
        cloud_cover_pct=Decimal("12.50"),
    )
    assert ev.event_name == "imagery.scene_discovered.v1"
    assert ev.cloud_cover_pct == Decimal("12.50")


def test_scene_ingested_carries_stac_item_id() -> None:
    ev = SceneIngestedV1(
        job_id=uuid4(),
        block_id=uuid4(),
        scene_id="abc",
        stac_item_id="sentinel_hub/s2_l2a/abc/deadbeef",
        valid_pixel_pct=Decimal("88.40"),
    )
    assert ev.event_name == "imagery.scene_ingested.v1"
    assert ev.stac_item_id.startswith("sentinel_hub/")


def test_scene_skipped_with_each_reason() -> None:
    for reason in ("cloud", "duplicate", "out_of_window"):
        ev = SceneSkippedV1(job_id=uuid4(), reason=reason)
        assert ev.event_name == "imagery.scene_skipped.v1"
        assert ev.reason == reason


def test_ingestion_failed_carries_error() -> None:
    ev = IngestionFailedV1(job_id=uuid4(), error="connection_reset_by_peer")
    assert ev.event_name == "imagery.ingestion_failed.v1"
    assert ev.error == "connection_reset_by_peer"


def test_index_aggregated_event() -> None:
    ev = IndexAggregatedV1(
        block_id=uuid4(),
        index_code="ndvi",
        time=datetime.now(UTC),
        valid_pixel_pct=Decimal("76.10"),
    )
    assert ev.event_name == "imagery.index_aggregated.v1"
    assert ev.index_code == "ndvi"
