"""A cloudy pass must be RECORDED, not erased.

The cloud cap used to be handed to the provider's own search as an
``eo:cloud_cover<=N`` filter. That does not reject a scene — it makes the
scene never have existed: no job row, no entry on the timeline, no reason.

The scene strip is built to say "cloudy" over a gap precisely so an operator
can tell weather from a broken pipeline (`list_farm_scene_days` says so in as
many words), and it cannot say anything about a pass it was never told about.

Measured on prod: greenFarm_Test's subscriptions carry a cap of **0**, so a
single cloud anywhere in a 110 km Sentinel-2 tile deleted the whole pass.
Sixteen scenes survived three months under an almost cloudless sky, with
unexplained gaps of 12 and 20 days. Every surviving job reads exactly `0.0%`
cloud, which is the tell — nothing else could ever have been discovered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery import tasks as imagery_tasks
from app.modules.imagery.providers.protocol import DiscoveredScene

from .test_ingestion_pipeline import _set_up_subscription

pytestmark = [pytest.mark.integration]


class _RecordingProvider:
    """Returns every scene, and remembers how it was asked."""

    code = "sentinel_hub"

    def __init__(self, scenes: tuple[DiscoveredScene, ...], seen: list[dict[str, Any]]) -> None:
        self._scenes = scenes
        self._seen = seen

    async def discover(self, **kwargs: Any) -> tuple[DiscoveredScene, ...]:
        self._seen.append(kwargs)
        return self._scenes

    async def aclose(self) -> None:
        pass


def _scene(name: str, day: int, cloud: str) -> DiscoveredScene:
    return DiscoveredScene(
        scene_id=name,
        scene_datetime=datetime(2026, 3, day, 8, 30, tzinfo=UTC),
        cloud_cover_pct=Decimal(cloud),
        geometry_geojson={"type": "Polygon", "coordinates": []},
    )


async def _jobs(session: AsyncSession, schema: str) -> dict[str, tuple[str, Any]]:
    rows = (
        await session.execute(
            text(
                f'SELECT scene_id, status, cloud_cover_pct FROM "{schema}".'
                "imagery_ingestion_jobs ORDER BY scene_datetime"
            )
        )
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


@pytest.mark.asyncio
async def test_an_over_cap_pass_is_recorded_with_its_cloud_percentage(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The greenFarm_Test shape: a cap of 0 against a partly cloudy sky."""
    sub_id, _block_id, schema, _product_id = await _set_up_subscription(
        admin_session, slug="cloud-cap-visible"
    )
    await admin_session.execute(
        text(
            f'UPDATE "{schema}".imagery_aoi_subscriptions '
            "SET cloud_cover_max_pct = 0 WHERE id = :id"
        ),
        {"id": sub_id},
    )
    await admin_session.commit()

    seen: list[dict[str, Any]] = []
    scenes = (
        _scene("CLEAR_0301", 1, "0.00"),
        _scene("HAZY_0304", 4, "12.50"),
        _scene("CLOUDY_0307", 7, "88.00"),
    )
    imagery_tasks.set_provider_factory(lambda _code: _RecordingProvider(scenes, seen))
    monkeypatch.setattr(imagery_tasks.acquire_scene, "delay", lambda *a, **k: None)

    try:
        result = await imagery_tasks._discover_scenes_async(sub_id, schema)
    finally:
        imagery_tasks.set_provider_factory(None)

    # The search itself carried no cloud filter, so the provider could not
    # have hidden anything from us.
    assert len(seen) == 1
    assert seen[0].get("max_cloud_cover_pct") is None

    assert result["discovered"] == 3
    assert result["queued"] == 1
    assert result["skipped_cloud"] == 2

    jobs = await _jobs(admin_session, schema)
    # Queued for acquisition — `acquire_scene.delay` is stubbed, so it stops
    # here rather than running.
    assert jobs["CLEAR_0301"][0] == "pending"
    # Both cloudy passes exist, each carrying the number that explains it.
    # Before this, neither row was ever written and the timeline simply had
    # a hole where 4 and 7 March should be.
    assert jobs["HAZY_0304"][0] == "skipped_cloud"
    assert float(jobs["HAZY_0304"][1]) == 12.5
    assert jobs["CLOUDY_0307"][0] == "skipped_cloud"
    assert float(jobs["CLOUDY_0307"][1]) == 88.0


@pytest.mark.asyncio
async def test_the_platform_ceiling_still_bounds_a_permissive_farm(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-farm cap can lower what is pulled, never raise it.

    The provider filter used to be the subscription's cap while the local
    check was the platform setting, so what was actually fetched was the
    lower of the two. Keeping the setting as a ceiling means dropping the
    server-side filter cannot spend more at the provider than before —
    raising a farm above the platform default stays a deliberate act.
    """
    sub_id, _block_id, schema, _product_id = await _set_up_subscription(
        admin_session, slug="cloud-cap-ceiling"
    )
    await admin_session.execute(
        text(
            f'UPDATE "{schema}".imagery_aoi_subscriptions '
            "SET cloud_cover_max_pct = 95 WHERE id = :id"
        ),
        {"id": sub_id},
    )
    await admin_session.commit()

    seen: list[dict[str, Any]] = []
    # 70% sits under the farm's own 95 but over the platform default of 60.
    scenes = (_scene("MURKY_0311", 11, "70.00"),)
    imagery_tasks.set_provider_factory(lambda _code: _RecordingProvider(scenes, seen))
    monkeypatch.setattr(imagery_tasks.acquire_scene, "delay", lambda *a, **k: None)

    try:
        result = await imagery_tasks._discover_scenes_async(sub_id, schema)
    finally:
        imagery_tasks.set_provider_factory(None)

    assert result["queued"] == 0
    assert result["skipped_cloud"] == 1
    jobs = await _jobs(admin_session, schema)
    assert jobs["MURKY_0311"][0] == "skipped_cloud"
