import { test, expect } from "../fixtures";

/**
 * The console's one structural rule: the map never unmounts.
 *
 * Selecting a pass, picking a block and editing all happen around a map that
 * stays where it is. When it does unmount, MapLibre is rebuilt and re-frames
 * the farm, so every click on the date bar makes the whole view flash and
 * zoom — which is how it was reported.
 *
 * The regression that made it happen: the farm summary query gained the
 * as-of instant in its key, so each date was a new key with no cached data,
 * and the page's `summaryQ.isLoading` branch replaced the entire console with
 * a "loading this farm" message. `placeholderData: keepPreviousData` is what
 * holds the previous answer while the next one loads.
 *
 * The assertion is on the DOM node itself rather than on the absence of a
 * loading message. A remount that happened to be fast enough to miss would
 * still be a remount.
 */

const FARM_ID = "33333333-3333-7333-8333-333333333333";
const BLOCK_ID = "55555555-5555-7555-8555-555555555555";
const W = 31.0;
const E = 31.004;
const S = 30.5;
const N = 30.504;

const farmDetail = {
  id: FARM_ID,
  code: "E2E",
  name: "E2E Farm",
  area_m2: 830_000,
  boundary: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [W, S],
          [E, S],
          [E, N],
          [W, N],
          [W, S],
        ],
      ],
    ],
  },
  centroid: { type: "Point", coordinates: [(W + E) / 2, (S + N) / 2] },
  active_from: "2026-01-01",
  active_to: null,
  is_active: true,
  governorate: null,
  district: null,
  nearest_city: null,
  primary_water_source: null,
  tags: [],
};

const block = {
  id: BLOCK_ID,
  farm_id: FARM_ID,
  code: "B-01",
  name: "North ridge",
  unit_type: "block",
  area_m2: 420_080,
  is_active: true,
  boundary: {
    type: "Polygon",
    coordinates: [
      [
        [W, S],
        [E, S],
        [E, N],
        [W, N],
        [W, S],
      ],
    ],
  },
};

/** Six passes, five days apart, all inside the default 30-day window. */
const scenes = Array.from({ length: 6 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 7, 24));
  d.setUTCDate(d.getUTCDate() - i * 5);
  const day = d.toISOString().slice(0, 10);
  return {
    scene_date: day,
    at: `${day}T08:30:00Z`,
    succeeded_count: 1,
    skipped_cloud_count: 0,
    computed_count: 1,
    cloud_cover_pct: null,
    no_reading_pct: "2.0",
  };
});

test("switching the date does not unmount the map", async ({ authedPage }) => {
  await authedPage.route(`**/api/v1/farms/${FARM_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(farmDetail) }),
  );
  await authedPage.route(new RegExp(`/api/v1/farms/${FARM_ID}/blocks(\\?|$)`), (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [block], next_cursor: null }),
    }),
  );
  // Deliberately slow. The whole point is what the console shows WHILE the
  // as-of summary is in flight; answered instantly, a remount would be too
  // quick to catch.
  await authedPage.route(new RegExp(`/api/v1/farms/${FARM_ID}/blocks/summary`), async (r) => {
    await new Promise((f) => setTimeout(f, 1200));
    await r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        units: [
          {
            id: BLOCK_ID,
            health: "watch",
            alert_count: 1,
            alert_severity: "watch",
            alert_action_type: "spray",
            ndvi_current: 0.32,
            ndre_current: null,
            ndwi_current: null,
            grid_product_id: null,
          },
        ],
      }),
    });
  });
  await authedPage.route(new RegExp(`/api/v1/farms/${FARM_ID}/scenes`), (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: scenes, median_gap_days: 5 }),
    }),
  );
  await authedPage.route("https://server.arcgisonline.com/**", (r) => r.abort());

  await authedPage.setViewportSize({ width: 1500, height: 880 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  await authedPage.waitForSelector("canvas.maplibregl-canvas");

  // Stamp the live canvas. A remount builds a new element, and the stamp goes
  // with the old one.
  await authedPage.evaluate(() => {
    const c = document.querySelector("canvas.maplibregl-canvas") as HTMLElement;
    c.dataset.apStamp = "first";
  });

  const older = scenes[3].scene_date;
  await authedPage
    .getByRole("option", { name: new RegExp(String(Number(older.slice(8, 10)))) })
    .first()
    .click();

  // Through the in-flight window and out the other side.
  await expect(authedPage).toHaveURL(/scene=/, { timeout: 5000 });
  await authedPage.waitForTimeout(600);
  const midFlight = await authedPage.evaluate(
    () =>
      (document.querySelector("canvas.maplibregl-canvas") as HTMLElement | null)?.dataset.apStamp ??
      null,
  );
  expect(midFlight, "the map unmounted while the new date was loading").toBe("first");

  await authedPage.waitForTimeout(1500);
  const settled = await authedPage.evaluate(
    () =>
      (document.querySelector("canvas.maplibregl-canvas") as HTMLElement | null)?.dataset.apStamp ??
      null,
  );
  expect(settled, "the map unmounted once the new date arrived").toBe("first");

  // And the farm is still on screen throughout — no full-page loading state.
  await expect(authedPage.getByText("E2E Farm").first()).toBeVisible();
});
