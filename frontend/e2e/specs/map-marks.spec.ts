import { test, expect } from "../fixtures";

/**
 * Reproduction: clicking a field-flag pennant or a signal diamond on the
 * Farm Console map opens the panel for that mark.
 *
 * Unlike the other console spec, this one DOES need MapLibre to render:
 * the marks are symbol layers and the click path is MapLibre's own
 * hit-testing, so nothing below the WebGL canvas can be asserted in jsdom.
 * Headless Chromium runs MapLibre on SwiftShader, which is enough.
 *
 * If these fail in a batch with `waitForMark` timing out and the map never
 * mounting, kill the reused Vite dev server before debugging anything else —
 * `playwright.config.ts` sets `reuseExistingServer`, and a long-lived one
 * serves a stale module graph after edits that add imports or hooks. A clean
 * server runs this file in about 30 seconds.
 */

const FARM_ID = "33333333-3333-7333-8333-333333333333";
const BLOCK_ID = "55555555-5555-7555-8555-555555555555";
const FLAG_ID = "66666666-6666-7666-8666-666666666666";
const OBS_ID = "77777777-7777-7777-8777-777777777777";
const DEF_ID = "88888888-8888-7888-8888-888888888888";
const PRODUCT_ID = "99999999-9999-7999-8999-999999999999";

// One square block. The flag sits well left of centre and the observation
// well right of it, so the two marks cannot collide with each other or with
// the block's name label.
const W = 31.0;
const E = 31.002;
const S = 30.5;
const N = 30.502;

const FLAG_LON = 31.0005;
const FLAG_LAT = 30.501;
const OBS_LON = 31.0015;
const OBS_LAT = 30.501;

const farmDetail = {
  id: FARM_ID,
  code: "E2E",
  name: "E2E Farm",
  area_m2: 420_083,
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
  area_m2: 42_008,
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

const flag = {
  id: FLAG_ID,
  farm_id: FARM_ID,
  block_id: BLOCK_ID,
  block_name: "North ridge",
  note: "Aphids on the western rows",
  severity: "warning",
  status: "open",
  point: { type: "Point", coordinates: [FLAG_LON, FLAG_LAT] },
  accuracy_m: 5,
  pin_until: "2099-01-01T00:00:00Z",
  is_pinned: true,
  raised_by: "11111111-1111-7111-8111-111111111111",
  raised_by_name: "Scout One",
  closed_at: null,
  closed_by: null,
  closed_by_name: null,
  close_reason: null,
  comment_count: 0,
  photos: [],
  comments: [],
  created_at: "2026-08-20T06:00:00Z",
  updated_at: "2026-08-20T06:00:00Z",
};

const signalDef = {
  id: DEF_ID,
  code: "leaf_wetness",
  name: "Leaf wetness",
  value_kind: "numeric",
  is_active: true,
};

const observation = {
  id: OBS_ID,
  time: "2026-08-21T07:30:00Z",
  signal_definition_id: DEF_ID,
  signal_code: "leaf_wetness",
  farm_id: FARM_ID,
  block_id: BLOCK_ID,
  value_numeric: "12.5",
  value_categorical: null,
  value_event: null,
  value_boolean: null,
  value_geopoint: null,
  attachment_s3_key: null,
  attachment_download_url: null,
  notes: null,
  recorded_by: "11111111-1111-7111-8111-111111111111",
  inserted_at: "2026-08-21T07:31:00Z",
  location_mode: "free_point",
  location_point: { longitude: OBS_LON, latitude: OBS_LAT },
};

async function mockConsole(
  page: import("@playwright/test").Page,
  opts: { gridded?: boolean; alerting?: boolean; entityObservations?: number } = {},
): Promise<void> {
  await page.route(`**/api/v1/farms/${FARM_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(farmDetail) }),
  );
  await page.route(new RegExp(`/api/v1/farms/${FARM_ID}/blocks(\\?|$)`), (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [block], next_cursor: null }),
    }),
  );
  await page.route(new RegExp(`/api/v1/farms/${FARM_ID}/blocks/summary`), (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        units: [
          {
            id: BLOCK_ID,
            health: "ok",
            alert_count: opts.alerting ? 2 : 0,
            alert_severity: opts.alerting ? "critical" : null,
            alert_action_type: opts.alerting ? "inspect" : null,
            ndvi_current: null,
            ndre_current: null,
            ndwi_current: null,
            grid_product_id: opts.gridded ? PRODUCT_ID : null,
          },
        ],
      }),
    }),
  );
  await page.route(`**/api/v1/farms/${FARM_ID}/field-flags**`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([flag]) }),
  );
  await page.route(`**/api/v1/field-flags/${FLAG_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(flag) }),
  );
  await page.route("**/api/v1/signals/definitions**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([signalDef]) }),
  );
  await page.route("**/api/v1/signals/observations**", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        opts.entityObservations
          ? Array.from({ length: opts.entityObservations }, (_, i) => ({
              ...observation,
              id: `${OBS_ID.slice(0, -1)}${i}`,
              // No coordinate of its own — the shape production is full of.
              location_mode: "entity",
              location_point: null,
              time: `2026-08-1${i}T07:30:00Z`,
            }))
          : [observation],
      ),
    }),
  );
  // The basemap is irrelevant to hit-testing and slow, so it is cut off.
  //
  // The GLYPH endpoint is deliberately left alone. The alert chip carries a
  // count, so it cannot draw until fonts arrive — and the whole point of this
  // file is that the chip is the mark the diamond has to survive being placed
  // beside. Aborting glyphs would remove the contest the test exists to run.
  await page.route("https://server.arcgisonline.com/**", (r) => r.abort());
}

/**
 * Screen point for a lon/lat, read out of the live MapLibre instance.
 *
 * MapCanvas keeps the map private, so the map is recovered from the canvas
 * element the way MapLibre itself does in its tests.
 */
async function projectPoint(
  page: import("@playwright/test").Page,
  lon: number,
  lat: number,
): Promise<{ x: number; y: number }> {
  return page.evaluate(
    ([lng, la]) => {
      const w = window as unknown as {
        __apMap?: {
          project: (c: [number, number]) => { x: number; y: number };
          getContainer: () => HTMLElement;
        };
      };
      const map = w.__apMap;
      if (!map) throw new Error("map instance not exposed");
      const p = map.project([lng as number, la as number]);
      const rect = map.getContainer().getBoundingClientRect();
      return { x: rect.left + p.x, y: rect.top + p.y };
    },
    [lon, lat],
  );
}

/**
 * Wait until MapLibre has actually PLACED a symbol on `layerId`.
 *
 * A fixed sleep is not enough here and never was: the marks arrive after the
 * style loads, after the overlay query resolves, and after a placement pass
 * that only runs once the glyph endpoint answers. Under two parallel workers
 * that chain routinely runs past three seconds.
 *
 * Waiting on `queryRenderedFeatures` is also the assertion that matters —
 * a symbol MapLibre did not place is not clickable, so "placed" and
 * "hit-testable" are the same question.
 */
async function waitForMark(page: import("@playwright/test").Page, layerId: string): Promise<void> {
  await page.waitForFunction(
    (id) => {
      const m = (
        window as unknown as {
          __apMap?: {
            getLayer: (i: string) => unknown;
            queryRenderedFeatures: (o: unknown) => unknown[];
            isMoving: () => boolean;
            isZooming: () => boolean;
          };
        }
      ).__apMap;
      if (!m || !m.getLayer(id)) return false;
      // Settled, not merely painted. The console frames the farm at map
      // construction and fits again when the summary lands, so a click
      // computed while the camera is still easing lands on ground that has
      // moved by the time the event is dispatched — which is exactly the
      // flake a fixed sleep used to hide.
      if (m.isMoving() || m.isZooming()) return false;
      return m.queryRenderedFeatures({ layers: [id] }).length > 0;
    },
    layerId,
    { timeout: 30_000 },
  );
}

const FLAG_LAYER_ID = "field-flag-symbol";
const SIGNAL_LAYER_ID = "signal-overlay-symbol";

/**
 * The console as production actually serves it: the block carries a sub-block
 * grid, so `showGrid` latches ON and the heatmap covers the whole block. This
 * is the state every real farm opens in and the bare-farm tests above never
 * reach.
 */
async function mockGrid(page: import("@playwright/test").Page): Promise<void> {
  const cells: Record<string, unknown>[] = [];
  const STEP = 0.0005;
  let i = 0;
  for (let lon = W; lon < E - 1e-9; lon += STEP) {
    for (let lat = S; lat < N - 1e-9; lat += STEP) {
      i += 1;
      cells.push({
        cell_id: `cell-${i}`,
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [lon, lat],
              [lon + STEP, lat],
              [lon + STEP, lat + STEP],
              [lon, lat + STEP],
              [lon, lat],
            ],
          ],
        },
        mean: "0.42",
        centroid_lat: lat + STEP / 2,
        centroid_lon: lon + STEP / 2,
        time: "2026-08-21T00:00:00Z",
      });
    }
  }
  await page.route(new RegExp(`/api/v1/farms/${FARM_ID}/grid-cells`), (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        blocks: [{ block_id: BLOCK_ID, product_id: PRODUCT_ID, cells }],
      }),
    }),
  );
}

test("clicking a field-flag pennant opens the flag panel, grid overlay on", async ({
  authedPage,
}) => {
  await mockConsole(authedPage, { gridded: true });
  await mockGrid(authedPage);
  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  await waitForMark(authedPage, FLAG_LAYER_ID);

  const p = await projectPoint(authedPage, FLAG_LON, FLAG_LAT);
  await authedPage.mouse.click(p.x, p.y - 12);

  await expect(authedPage.getByText("Aphids on the western rows")).toBeVisible({ timeout: 5000 });
  // And nothing else opened over it.
  await expect(authedPage.getByText(/Cell$|Grid cell/i)).toHaveCount(0);
});

test("clicking a signal diamond opens the observation panel, grid overlay on", async ({
  authedPage,
}) => {
  await mockConsole(authedPage, { gridded: true });
  await mockGrid(authedPage);
  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  await waitForMark(authedPage, SIGNAL_LAYER_ID);

  const p = await projectPoint(authedPage, OBS_LON, OBS_LAT);
  await authedPage.mouse.click(p.x, p.y);

  await expect(authedPage).toHaveURL(/signal_obs=/, { timeout: 5000 });
  await expect(authedPage.getByText("Signal observation")).toBeVisible({ timeout: 5000 });
});

test("clicking a field-flag pennant opens the flag panel", async ({ authedPage }) => {
  await mockConsole(authedPage);
  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  await waitForMark(authedPage, FLAG_LAYER_ID);

  const p = await projectPoint(authedPage, FLAG_LON, FLAG_LAT);
  // The pennant is anchored at its foot, so the flag body sits ABOVE the
  // coordinate.
  await authedPage.mouse.click(p.x, p.y - 12);

  await expect(authedPage.getByText("Aphids on the western rows")).toBeVisible({ timeout: 5000 });
});

test("clicking a signal diamond opens the observation panel", async ({ authedPage }) => {
  await mockConsole(authedPage);
  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  await waitForMark(authedPage, SIGNAL_LAYER_ID);

  const p = await projectPoint(authedPage, OBS_LON, OBS_LAT);
  await authedPage.mouse.click(p.x, p.y);

  await expect(authedPage).toHaveURL(/signal_obs=/, { timeout: 5000 });
  await expect(authedPage.getByText("Signal observation")).toBeVisible({ timeout: 5000 });
});

/**
 * The shape production actually had, and the regression this file exists for.
 *
 * Bashier Elkhier: 36 blocks, every one carrying an open alert, and 145
 * observations recorded in `entity` mode — no coordinate of their own, so
 * each one falls back to its block's centroid. That is the same point the
 * alert chip and the block's name label are anchored to.
 *
 * #581 put all four marker layers into collision, with the observation
 * diamond placed LAST. So on every block the diamond lost its contest and was
 * never drawn — and MapLibre does not return a symbol it did not place from
 * `queryRenderedFeatures`, so the mark was invisible AND unclickable, with no
 * error anywhere. Four readings stacked on one point made it worse: even with
 * room, MapLibre can place only one of four identical points.
 *
 * This test fails on 1d0ed727 and passes on the fix.
 */
test("a stacked entity-mode observation stays clickable on an alerting block", async ({
  authedPage,
}) => {
  await mockConsole(authedPage, { alerting: true, entityObservations: 4 });
  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  // This is the regression in one line: before the fix the diamond is never
  // placed, so this wait times out.
  await waitForMark(authedPage, SIGNAL_LAYER_ID);

  // The diamond is drawn down-and-left of the block anchor, clear of the
  // chip; the block centroid is the vertex average of the square.
  const p = await projectPoint(authedPage, (W + E) / 2, (S + N) / 2);
  await authedPage.mouse.click(p.x - 14, p.y + 22);

  await expect(authedPage).toHaveURL(/signal_obs=/, { timeout: 5000 });
  await expect(authedPage.getByText("Signal observation")).toBeVisible({ timeout: 5000 });
  // And the three readings buried under it are reachable, not lost.
  await expect(authedPage.getByText(/4 readings on this spot/i)).toBeVisible({ timeout: 5000 });
});
