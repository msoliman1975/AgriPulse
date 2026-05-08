import { test, expect } from "../fixtures";

/**
 * Golden-path smoke. The point isn't deep coverage — it's that the
 * production bundle boots, the auth gate accepts a sessionStorage user,
 * and the primary navigation surfaces render without throwing.
 *
 * Deeper flows (alert ack, recommendation apply, signal log) belong in
 * sibling spec files that mock the relevant endpoints.
 */

test.describe("App shell smoke", () => {
  test("renders the shell once authenticated", async ({ authedPage }) => {
    await authedPage.goto("/");
    // The home page is gated behind ProtectedRoute; if our fake OIDC
    // user wasn't accepted we'd land on /login and `nav` would be absent.
    const nav = authedPage.getByRole("navigation", { name: /primary/i });
    await expect(nav).toBeVisible();
  });

  test("navigates to the farms list", async ({ authedPage }) => {
    await authedPage.goto("/");
    await authedPage.getByRole("link", { name: /land units/i }).click();
    await expect(authedPage).toHaveURL(/\/farms$/);
    // Main landmark stays mounted across the route change.
    await expect(authedPage.getByRole("main")).toBeVisible();
  });

  test("language switch flips html.dir to rtl when Arabic selected", async ({
    authedPage,
  }) => {
    // i18n init reads the saved language from `missionagre.lang` —
    // see src/i18n/index.ts (lookupLocalStorage). Setting it before
    // page load makes Arabic the active language at boot, which fires
    // syncHtmlAttributes("ar") → <html dir="rtl">.
    await authedPage.addInitScript(() => {
      window.localStorage.setItem("missionagre.lang", "ar");
    });
    await authedPage.goto("/");
    await expect
      .poll(() => authedPage.evaluate(() => document.documentElement.dir))
      .toBe("rtl");
  });
});
