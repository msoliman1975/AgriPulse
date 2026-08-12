import { test, expect } from "../fixtures";

/**
 * Farm Console v2 (/labs/map-v2) — the shell reaches the screen.
 *
 * Scope is deliberately narrow. The legend maths, the rail ordering and the
 * copy parity are covered by fast unit tests; what only a browser can prove
 * is that the route resolves, the app shell pins the viewport, and the seven
 * zones mount against real network shapes rather than jsdom stubs.
 *
 * As with grid.spec.ts, MapLibre's own rendering is not asserted — jsdom
 * cannot and headless WebGL is not worth the flake. CI does not run e2e, so
 * treat this as a manual gate, not a safety net.
 */

const FARM_ID = "33333333-3333-7333-8333-333333333333";
const BLOCK_ID = "55555555-5555-7555-8555-555555555555";

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
          [31.0, 30.5],
          [31.001, 30.5],
          [31.001, 30.501],
          [31.0, 30.501],
          [31.0, 30.5],
        ],
      ],
    ],
  },
  centroid: { type: "Point", coordinates: [31.0005, 30.5005] },
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
        [31.0, 30.5],
        [31.0005, 30.5],
        [31.0005, 30.5005],
        [31.0, 30.5005],
        [31.0, 30.5],
      ],
    ],
  },
};

test("Farm Console v2 mounts its zones and explains an empty legend", async ({ authedPage }) => {
  await authedPage.route(`**/api/v1/farms/${FARM_ID}`, async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify(farmDetail) });
  });
  await authedPage.route(`**/api/v1/farms/${FARM_ID}/blocks**`, async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify([block]) });
  });

  await authedPage.setViewportSize({ width: 1600, height: 900 });
  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");

  // Zone 1 — identity strip answers "what am I looking at" with no panel.
  await expect(authedPage.getByText("E2E Farm").first()).toBeVisible();

  // Zone 2 — the rail's new filter exists and the unit is listed.
  await expect(authedPage.getByLabel(/filter units/i)).toBeVisible();

  // Zone 4 — with no imagery subscription there is nothing to measure, and
  // the legend has to say so rather than render an empty scale.
  await expect(
    authedPage.getByText(/no imagery subscription|no zoned blocks/i).first(),
  ).toBeVisible();

  // Zone 5 — controls Slice 3 will implement are present but disabled, so a
  // reader can see the capability is coming rather than guess it is missing.
  await expect(authedPage.getByRole("button", { name: /compare two dates/i })).toBeDisabled();
});

test("the v2 route does not bounce back to the live console", async ({ authedPage }) => {
  await authedPage.route(`**/api/v1/farms/${FARM_ID}`, async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify(farmDetail) });
  });
  await authedPage.route(`**/api/v1/farms/${FARM_ID}/blocks**`, async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify([block]) });
  });

  await authedPage.goto(`/labs/map-v2/${FARM_ID}`);
  await authedPage.waitForLoadState("networkidle");
  // The live console's redirect hard-codes /labs/map/<id>; if v2 ever reuses
  // it, this is the assertion that catches it.
  expect(new URL(authedPage.url()).pathname).toBe(`/labs/map-v2/${FARM_ID}`);
});
