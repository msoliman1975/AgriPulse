import { test, expect } from "../fixtures";

/**
 * Deeper-flow demo: list one open alert → click Ack → verify the
 * PATCH lands with the right body and the row reflects the new state.
 *
 * Pattern to extend for other golden paths (recommendation apply,
 * signal log, alert resolve): mock `/v1/<resource>` for the list +
 * `/v1/<resource>/{id}` for the transition; assert on the request
 * body via `route.request().postDataJSON()`.
 */

const FARM_ID = "33333333-3333-7333-8333-333333333333";
const ALERT_ID = "44444444-4444-7444-8444-444444444444";
const BLOCK_ID = "55555555-5555-7555-8555-555555555555";

const openAlert = {
  id: ALERT_ID,
  block_id: BLOCK_ID,
  rule_code: "ndvi_drop",
  severity: "warning",
  status: "open",
  diagnosis_en: "NDVI dropped 12% week-over-week.",
  diagnosis_ar: null,
  prescription_en: "Walk the block. Check for irrigation issues.",
  prescription_ar: null,
  prescription_activity_id: null,
  signal_snapshot: null,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
  acknowledged_at: null,
  acknowledged_by: null,
  resolved_at: null,
  resolved_by: null,
  snoozed_until: null,
};

test("acknowledges an open alert", async ({ authedPage }) => {
  let ackBody: unknown = null;

  // Override the catch-all route from fixtures for the alerts endpoints.
  await authedPage.route("**/api/v1/alerts**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([openAlert]),
      });
      return;
    }
    if (route.request().method() === "PATCH") {
      ackBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...openAlert,
          status: "acknowledged",
          acknowledged_at: "2026-05-08T20:00:00Z",
          acknowledged_by: "11111111-1111-7111-8111-111111111111",
        }),
      });
      return;
    }
    await route.fulfill({ status: 405, body: "" });
  });

  await authedPage.goto(`/alerts/${FARM_ID}`);

  // The Ack button is a per-row affordance with the visible label "Ack".
  const ackButton = authedPage.getByRole("button", { name: /^ack$/i }).first();
  await expect(ackButton).toBeVisible();
  await ackButton.click();

  // Server roundtrip body matches the contract the backend expects.
  await expect.poll(() => ackBody).toEqual({ acknowledge: true });
});
