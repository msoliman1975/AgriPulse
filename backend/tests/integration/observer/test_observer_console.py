"""Integration tests for the Observer console (/api/v1/admin/observer…).

Asserted against the seeded scenario in `conftest.Scenario`, so these are
exact-count tests rather than shape checks. See that module's docstring for
the farm being described and why it is seeded rather than discovered.

The scenario deliberately contains three states that a naive implementation
gets wrong, and each has a test here:

  * a scene that downloaded and then failed to compute — must show at the
    indices stage, not hide behind a green acquire count (#335);
  * an ungridded block — must be excluded from the cell denominator, not
    counted as four missing cell aggregates;
  * a cloud-skipped scene — must be removed from the acquire denominator,
    not counted as a provider failure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import WINDOW_FROM, WINDOW_TO, Scenario, build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/observer"


def _client(**context_kwargs: object) -> AsyncClient:
    context = make_context(**context_kwargs)  # type: ignore[arg-type]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _platform_client() -> AsyncClient:
    return _client(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)


def _support_client() -> AsyncClient:
    return _client(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_SUPPORT)


def _tenant_client(tenant_id: UUID) -> AsyncClient:
    return _client(
        user_id=uuid4(),
        tenant_id=tenant_id,
        tenant_role=TenantRole.TENANT_OWNER,
        platform_role=None,
    )


def _window() -> dict[str, str]:
    return {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()}


def _stages(body: dict) -> dict[str, dict]:
    return {s["key"]: s for s in body["stages"]}


# ---- access control -------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_owner_cannot_reach_any_observer_route(scenario: Scenario) -> None:
    """Observer reads across tenants; no tenant role may hold it.

    TenantOwner is the strongest tenant-scoped role, so refusing it refuses
    every weaker one — including on that user's *own* tenant, which is the
    case a scope bug would let through.
    """
    async with _tenant_client(scenario.tenant_id) as client:
        w = _window()
        paths = [
            f"{_BASE}/tenants",
            f"{_BASE}/tenants/{scenario.tenant_id}/farms",
            f"{_BASE}/tenants/{scenario.tenant_id}/farms/{scenario.farm_id}/products",
            f"{_BASE}/tenants/{scenario.tenant_id}/overview"
            f"?farm_id={scenario.farm_id}&from={w['from']}&to={w['to']}",
            f"{_BASE}/tenants/{scenario.tenant_id}/histogram"
            f"?farm_id={scenario.farm_id}&from={w['from']}&to={w['to']}",
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes"
            f"?farm_id={scenario.farm_id}&from={w['from']}&to={w['to']}",
        ]
        for path in paths:
            r = await client.get(path)
            assert r.status_code == 403, f"{path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_platform_support_can_read_the_overview(scenario: Scenario) -> None:
    """Read-only support staff hold `platform.observe_pipeline`.

    "Is this number right?" is asked by support far more often than by
    admins, and the capability is read-only precisely so it can be granted
    that widely.
    """
    async with _support_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/overview",
            params={"farm_id": str(scenario.farm_id), **_window()},
        )
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_unknown_tenant_is_404(scenario: Scenario) -> None:
    del scenario
    async with _platform_client() as client:
        r = await client.get(f"{_BASE}/tenants/{uuid4()}/farms")
        assert r.status_code == 404


# ---- pickers --------------------------------------------------------------


@pytest.mark.asyncio
async def test_farm_picker_reports_what_is_configured(scenario: Scenario) -> None:
    async with _platform_client() as client:
        farms = (await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/farms")).json()
        farm = next(f for f in farms if f["id"] == str(scenario.farm_id))
        assert farm["block_count"] == 2
        assert farm["blocks_with_imagery_sub"] == 2
        # Only block A is gridded — this is what tells an operator that a
        # zero cell count on block B is expected rather than broken.
        assert farm["blocks_with_grid"] == 1
        assert farm["has_weather_sub"] is False
        assert farm["first_scene_at"] is not None
        assert farm["last_scene_at"] is not None


@pytest.mark.asyncio
async def test_product_picker_joins_out_for_the_provider_code(
    scenario: Scenario,
) -> None:
    """`imagery_products` carries no `provider_code` — it must be joined."""
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/farms/{scenario.farm_id}/products"
        )
        assert r.status_code == 200, r.text
        products = r.json()
        assert len(products) == 1
        assert products[0]["code"] == "s2_l2a"
        assert products[0]["provider_code"] == "sentinel_hub"
        assert "ndvi" in products[0]["supported_indices"]


# ---- the ribbon -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ribbon_counts_match_the_seeded_pipeline(scenario: Scenario) -> None:
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/overview",
            params={"farm_id": str(scenario.farm_id), **_window()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["block_count"] == 2
        s = _stages(body)

        # 4 + 1 failed + 1 skipped on A, 2 on B.
        assert s["discovered"]["count"] == 8
        assert s["discovered"]["detail"] == {
            "failed": 1,
            "in_flight": 0,
            "skipped": 1,
        }

        # 6 succeeded of 7 that were not skipped — the failed one is the gap.
        assert s["acquired"]["count"] == 6
        assert s["acquired"]["expected"] == 7
        assert s["acquired"]["shortfall"] == 1

        # 5 scenes wrote aggregates, of 6 acquired: the missing one is the
        # "downloaded fine, compute_indices died" case.
        assert s["indices"]["count"] == 5
        assert s["indices"]["expected"] == 6
        assert s["indices"]["detail"]["aggregate_rows"] == 35  # 5 scenes x 7 indices
        assert s["indices"]["detail"]["index_codes"] == 7


@pytest.mark.asyncio
async def test_a_scene_that_downloaded_then_failed_to_compute_is_visible(
    scenario: Scenario,
) -> None:
    """#335: the job row says 'succeeded' because the *download* succeeded.

    If acquisition and computation shared a stage, this scene would be
    invisible — which is exactly how a dead compute task went unnoticed.
    """
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        s = _stages(body)
        assert s["acquired"]["verdict"] in {"warn", "bad"} or s["acquired"]["count"] == 6
        assert s["indices"]["shortfall"] == 1
        assert s["indices"]["verdict"] in {"warn", "bad"}


@pytest.mark.asyncio
async def test_ungridded_block_is_excluded_from_the_cell_denominator(
    scenario: Scenario,
) -> None:
    """The denominator that stops an ordinary farm reading as broken.

    Block B has no grid config, so its 2 succeeded scenes are not missing
    cell aggregates. `expected` must count only block A's 4 succeeded
    scenes — not all 6.
    """
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        cells = _stages(body)["cells"]
        assert cells["expected"] == 4, "ungridded block B leaked into the denominator"
        assert cells["count"] == 2
        assert cells["shortfall"] == 2


@pytest.mark.asyncio
async def test_a_farm_with_no_grid_at_all_reads_not_applicable(
    scenario: Scenario,
) -> None:
    """Narrowing to the ungridded block must not report a failure."""
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_b)],
                    **_window(),
                },
            )
        ).json()
        cells = _stages(body)["cells"]
        assert cells["expected"] == 0
        assert cells["verdict"] == "not_applicable"


@pytest.mark.asyncio
async def test_cloud_skipped_scenes_leave_the_acquire_denominator(
    scenario: Scenario,
) -> None:
    """A cloud-skipped scene was never going to be acquired.

    Counting it as a miss would make a cloudy month look like an outage.
    """
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        s = _stages(body)
        assert s["discovered"]["count"] - s["discovered"]["detail"]["skipped"] == (
            s["acquired"]["expected"]
        )


@pytest.mark.asyncio
async def test_block_filter_narrows_every_stage(scenario: Scenario) -> None:
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        s = _stages(body)
        assert body["block_count"] == 1
        assert s["discovered"]["count"] == 6  # 4 succeeded + 1 failed + 1 skipped
        assert s["indices"]["count"] == 3


@pytest.mark.asyncio
async def test_window_outside_the_scenario_is_all_zeros(scenario: Scenario) -> None:
    """Proves the time bounds are actually applied, interpolation and all."""
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={
                    "farm_id": str(scenario.farm_id),
                    "from": (WINDOW_TO + timedelta(days=1)).isoformat(),
                    "to": (WINDOW_TO + timedelta(days=30)).isoformat(),
                },
            )
        ).json()
        assert all(s["count"] == 0 for s in body["stages"])


@pytest.mark.asyncio
async def test_overview_refuses_a_window_wider_than_the_cap(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        now = datetime.now(UTC)
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/overview",
            params={
                "farm_id": str(scenario.farm_id),
                "from": (now - timedelta(days=4000)).isoformat(),
                "to": now.isoformat(),
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_unknown_farm_is_empty_not_an_error(scenario: Scenario) -> None:
    """A farm whose blocks are all gone is a reportable state, not a 404."""
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/overview",
            params={"farm_id": str(uuid4()), **_window()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["block_count"] == 0
        assert all(s["count"] == 0 for s in body["stages"])


@pytest.mark.asyncio
async def test_a_block_from_another_farm_cannot_widen_the_selection(
    scenario: Scenario, admin_session: object
) -> None:
    """Scope containment: `blocks` is a filter, never a way to cross farms."""
    del admin_session
    async with _platform_client() as client:
        # Ask for a farm that owns no blocks, naming a block that does exist.
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
            params={
                "farm_id": str(uuid4()),
                "blocks": [str(scenario.block_a)],
                **_window(),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json() == [], "a foreign block id leaked data across farms"


# ---- histogram ------------------------------------------------------------


@pytest.mark.asyncio
async def test_histogram_splits_computed_from_merely_acquired(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/histogram",
            params={"farm_id": str(scenario.farm_id), "bucket": "month", **_window()},
        )
        assert r.status_code == 200, r.text
        buckets = r.json()
        assert len(buckets) == 1
        b = buckets[0]
        assert b["total"] == 8
        assert b["computed"] == 5
        assert b["acquired_only"] == 1
        assert b["failed"] == 1
        assert b["skipped"] == 1
        assert b["pending"] == 0
        assert (
            b["computed"] + b["acquired_only"] + b["skipped"] + b["failed"] + b["pending"]
        ) == b["total"]


@pytest.mark.asyncio
async def test_histogram_buckets_are_ordered(scenario: Scenario) -> None:
    async with _platform_client() as client:
        buckets = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/histogram",
                params={"farm_id": str(scenario.farm_id), "bucket": "day", **_window()},
            )
        ).json()
        assert buckets == sorted(buckets, key=lambda x: x["bucket"])
        assert sum(x["total"] for x in buckets) == 8


@pytest.mark.asyncio
async def test_histogram_rejects_an_unsupported_bucket(scenario: Scenario) -> None:
    """The bucket is interpolated into `date_trunc`, so the set is closed."""
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/histogram",
            params={"farm_id": str(scenario.farm_id), "bucket": "century", **_window()},
        )
        assert r.status_code == 422, r.text


# ---- scene table ----------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_rows_distinguish_ungridded_from_missing_cells(
    scenario: Scenario,
) -> None:
    """`gridded` is the flag that stops `0/0` reading as a failure."""
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        assert len(rows) == 8
        by_block: dict[str, list[dict]] = {}
        for row in rows:
            by_block.setdefault(row["block_id"], []).append(row)

        for row in by_block[str(scenario.block_a)]:
            assert row["gridded"] is True
            assert row["cells_expected"] == 4
        for row in by_block[str(scenario.block_b)]:
            assert row["gridded"] is False
            assert row["cells_expected"] == 0
            assert row["cells_written"] == 0


@pytest.mark.asyncio
async def test_scene_rows_report_what_each_stage_produced(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        computed = [r for r in rows if r["indices_written"] > 0]
        assert len(computed) == 3
        assert all(r["indices_written"] == 7 for r in computed)
        # 2 of the 3 also wrote cells; a job with no aggregates must still
        # appear, with zeros, or the operator cannot find it.
        assert sorted(r["cells_written"] for r in rows) == [0, 0, 0, 0, 4, 4]
        assert rows == sorted(rows, key=lambda r: r["scene_datetime"], reverse=True)


@pytest.mark.asyncio
async def test_scene_filters_narrow_the_list(scenario: Scenario) -> None:
    async with _platform_client() as client:
        base = {"farm_id": str(scenario.farm_id), **_window()}

        failed = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={**base, "status": ["failed"]},
            )
        ).json()
        assert len(failed) == 1
        assert failed[0]["error_code"] == "provider_timeout"

        with_error = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={**base, "with_error": "true"},
            )
        ).json()
        assert len(with_error) == 1

        # Block B's scenes were seeded at 43.1% valid.
        low_valid = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={**base, "max_valid_pct": 50},
            )
        ).json()
        assert len(low_valid) == 2
        assert {r["block_id"] for r in low_valid} == {str(scenario.block_b)}


@pytest.mark.asyncio
async def test_scene_list_rejects_an_unknown_status_filter(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
            params={
                "farm_id": str(scenario.farm_id),
                "status": ["definitely_not_a_status"],
                **_window(),
            },
        )
        assert r.status_code == 422, r.text
        assert "definitely_not_a_status" in r.text


@pytest.mark.asyncio
async def test_expanded_row_returns_all_seven_indices(scenario: Scenario) -> None:
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        row = next(r for r in rows if r["indices_written"] == 7)
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/indices",
            params={
                "block_id": row["block_id"],
                "product_id": row["product_id"],
                "scene_time": row["scene_datetime"],
            },
        )
        assert r.status_code == 200, r.text
        indices = r.json()
        assert len(indices) == 7
        assert {i["index_code"] for i in indices} == {
            "ndvi",
            "ndwi",
            "evi",
            "savi",
            "ndre",
            "gndvi",
            "ndmi",
        }
        ndvi = next(i for i in indices if i["index_code"] == "ndvi")
        assert ndvi["valid_pixel_count"] == 3214
        assert ndvi["total_pixel_count"] == 3508
        # Generated column: 100 * 3214 / 3508.
        assert ndvi["valid_pixel_pct"] == pytest.approx(91.62, abs=0.01)


# ---- L2: scene detail ------------------------------------------------------


@pytest.mark.asyncio
async def test_scenes_indices_path_is_not_swallowed_by_the_job_id_route(
    scenario: Scenario,
) -> None:
    """`/scenes/indices` and `/scenes/{job_id}` share a prefix.

    FastAPI resolves by declaration order, so the literal path only wins
    because it is declared first. Reordering the router would turn this into
    a 422 ("indices is not a UUID") that no other test would catch.
    """
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        row = next(r for r in rows if r["indices_written"] == 7)
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/indices",
            params={
                "block_id": row["block_id"],
                "product_id": row["product_id"],
                "scene_time": row["scene_datetime"],
            },
        )
        assert r.status_code == 200, r.text
        assert len(r.json()) == 7


@pytest.mark.asyncio
async def test_scene_detail_resolves_the_grid_that_governed_the_scene(
    scenario: Scenario,
) -> None:
    """Not "the current grid" — the one whose valid-time range covers it."""
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        # Newest-first ordering puts the cloud-skipped scene at index 0, and
        # that one never wrote a raster — pick a scene that actually did.
        job_id = next(r for r in rows if r["stac_item_id"])["job_id"]
        r = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider_code"] == "sentinel_hub"
        assert body["product_code"] == "s2_l2a"
        assert body["grid"] is not None
        assert body["grid"]["cell_count"] == 4
        assert body["grid"]["cell_size_m"] == 40.0
        # The asset layout is the pipeline's, built by its own key builder.
        assert body["raw_asset_key"].endswith("/raw_bands.tif")
        assert body["raw_asset_key"].startswith("sentinel_hub/s2_l2a/")
        assert body["aoi_hash"] in body["raw_asset_key"]
        assert set(body["index_asset_keys"]) <= set(body["supported_indices"])
        # The mask ruleset is named and its classes are transmitted, so the
        # UI never has to hard-code which SCL values were dropped.
        assert body["mask_ruleset"] == "s2_scl_v1"
        assert set(body["mask_classes"]) == {0, 1, 3, 8, 9, 10, 11}


@pytest.mark.asyncio
async def test_scene_detail_on_an_ungridded_block_reports_no_grid(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_b)],
                    **_window(),
                },
            )
        ).json()
        r = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{rows[0]['job_id']}")
        assert r.status_code == 200, r.text
        assert r.json()["grid"] is None


@pytest.mark.asyncio
async def test_scene_detail_of_an_unknown_job_is_404(scenario: Scenario) -> None:
    async with _platform_client() as client:
        r = await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{uuid4()}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_pixel_explain_on_a_scene_with_no_raster_is_409_not_404(
    scenario: Scenario,
) -> None:
    """The scene exists; it just never produced a COG.

    A 404 would send the operator looking for a missing row when the real
    answer is "this job failed before it wrote anything".
    """
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "status": ["failed"],
                    **_window(),
                },
            )
        ).json()
        assert len(rows) == 1
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{rows[0]['job_id']}/pixel",
            params={"lon": 31.21, "lat": 30.01},
        )
        assert r.status_code == 409, r.text
        assert "no raw-bands COG" in r.text


@pytest.mark.asyncio
async def test_pixel_budget_on_a_scene_with_no_raster_is_409(
    scenario: Scenario,
) -> None:
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "status": ["skipped_cloud"],
                    **_window(),
                },
            )
        ).json()
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{rows[0]['job_id']}/pixel-budget"
        )
        assert r.status_code == 409, r.text


# ---- OBS-5: calculation lineage --------------------------------------------


@pytest.mark.asyncio
async def test_scene_detail_carries_calculation_history(scenario: Scenario) -> None:
    """`indices_calc_runs` is what makes a silent overwrite visible.

    The scenario seeds two runs for one scene under different calc versions —
    the shape a re-computation leaves behind. The aggregate row itself cannot
    show this: it is upserted on its composite key, so the second run simply
    replaced the first one's numbers.
    """
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        job_id = next(r for r in rows if r["scene_id"] == "S2A_OBS_A_00")["job_id"]
        body = (await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_id}")).json()

        runs = body["calc_runs"]
        assert len(runs) == 2
        # Newest first, so the version currently reflected in the aggregate
        # row is the one at the top.
        assert [r["calc_version"] for r in runs] == ["idx-2026.08", "idx-2026.03"]
        assert runs[0]["mask_ruleset"] == "s2_scl_v1"
        assert runs[0]["trigger"] == "live"
        assert runs[0]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_lineage_records_the_pixel_split_the_aggregate_cannot(
    scenario: Scenario,
) -> None:
    """masked vs no-data, which `block_index_aggregates` conflates.

    valid + masked + nodata must reconcile to the AOI footprint, or the
    "why is this only 43% valid?" answer is not an answer.
    """
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        job_id = next(r for r in rows if r["scene_id"] == "S2A_OBS_A_00")["job_id"]
        run = (await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_id}")).json()[
            "calc_runs"
        ][0]

        assert run["aoi_pixel_count"] == 3508
        assert run["masked_pixel_count"] == 239
        ndvi = run["per_index"]["ndvi"]
        assert ndvi["valid"] + ndvi["nodata"] + run["masked_pixel_count"] == (
            run["aoi_pixel_count"]
        )


@pytest.mark.asyncio
async def test_overview_reports_every_calc_version_in_the_window(
    scenario: Scenario,
) -> None:
    """Two methodologies in one trend line is a warning the UI must be able
    to render — and it can only be derived from the lineage table."""
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        versions = {v["calc_version"] for v in body["calc_versions"]}
        assert versions == {"idx-2026.08", "idx-2026.03"}
        for entry in body["calc_versions"]:
            assert entry["runs"] >= 1
            assert entry["first_scene_time"] is not None


@pytest.mark.asyncio
async def test_a_failed_execution_is_still_recorded(scenario: Scenario) -> None:
    """#335 died nine seconds in and reported nothing.

    A failed run row is the difference between "queued, no progress" and
    "attempted, and here is why it died".
    """
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/scenes",
                params={
                    "farm_id": str(scenario.farm_id),
                    "blocks": [str(scenario.block_a)],
                    **_window(),
                },
            )
        ).json()
        job_id = next(r for r in rows if r["scene_id"] == "S2A_OBS_A_03")["job_id"]
        runs = (await client.get(f"{_BASE}/tenants/{scenario.tenant_id}/scenes/{job_id}")).json()[
            "calc_runs"
        ]
        assert len(runs) == 1
        assert runs[0]["outcome"] == "failed"
        assert runs[0]["error"]
        # A failed run contributes no version to the overview's version list.
        assert runs[0]["per_index"] == {}
