#!/usr/bin/env node
// Post-deploy UI check: the platform Beta designer opens in prod and its
// Targeting tab works.
//
//   AGRIPULSE_SMOKE_USER=... AGRIPULSE_SMOKE_PASSWORD=... \
//     node scripts/ops/check-prod-beta-designer.cjs [tree-code] [screenshot-dir]
//
// Signs in through Keycloak as a platform admin, opens the Beta designer on
// `tree-code` (default: the first tree in the list), and checks that:
//   * the designer loads and shows the tabs Canvas, Targeting, Combinations,
//     Dry run;
//   * the Targeting tab shows the crop picker, at least one country checkbox
//     (the country list is fetched, so this waits for it) and the seven soil
//     textures.
// Read-only: it clicks tabs and nothing else. Never Save draft or Publish.
//
// Credentials come only from the environment. Do not write them to a file or
// commit them. The account must be a platform admin; the page is English-only
// checked, so use an account whose UI language is English.
//
// Needs network access to app.agripulse.cloud, api.agripulse.cloud and
// keycloak.agripulse.cloud. Honours HTTPS_PROXY. Uses `playwright` if it is
// installed, else the frontend's `@playwright/test`.
//
// Exit 0: all checks passed. Exit 1: a check failed (the step is printed and
// a screenshot saved). Exit 2: bad usage or missing credentials.

const path = require("node:path");
const fs = require("node:fs");

function loadChromium() {
  for (const mod of [
    "playwright",
    path.join(__dirname, "../../frontend/node_modules/@playwright/test"),
  ]) {
    try {
      return require(mod).chromium;
    } catch {
      // try the next one
    }
  }
  console.error("Playwright is not installed (`cd frontend && pnpm install`).");
  process.exit(2);
}

const APP = process.env.PROD_APP_URL || "https://app.agripulse.cloud";
const LIST = `${APP}/platform/decision-trees-beta`;
const TABS = ["Canvas", "Targeting", "Combinations", "Dry run"];
const SOILS = ["Sandy", "Sandy loam", "Loam", "Clay loam", "Clay", "Silty loam", "Silty clay"];

const user = process.env.AGRIPULSE_SMOKE_USER;
const pass = process.env.AGRIPULSE_SMOKE_PASSWORD;
const treeCode = process.argv[2] && process.argv[2] !== "-" ? process.argv[2] : null;
const outDir = process.argv[3] || ".";

if (!user || !pass) {
  console.error("Set AGRIPULSE_SMOKE_USER and AGRIPULSE_SMOKE_PASSWORD (a platform admin).");
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });

const log = (m) => console.log(`${new Date().toISOString().slice(11, 19)} ${m}`);

(async () => {
  const chromium = loadChromium();
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  const browser = await chromium.launch({ proxy });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  let step = "start";
  const fail = async (why) => {
    const shot = path.join(outDir, "beta-designer-fail.png");
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
    console.error(`FAIL at "${step}": ${why} (screenshot: ${shot})`);
    await browser.close();
    process.exit(1);
  };

  try {
    step = "sign in";
    await page.goto(treeCode ? `${LIST}/${treeCode}` : LIST, { waitUntil: "domcontentloaded" });
    const pw = page.locator('input[type="password"]');
    await pw.first().waitFor({ timeout: 30000 });
    await page.locator('input[type="email"], input[name="username"], #username').first().fill(user);
    await pw.first().fill(pass);
    await page.getByRole("button", { name: /sign in/i }).first().click();
    await pw.first().waitFor({ state: "detached", timeout: 30000 });
    log("signed in");

    if (!treeCode) {
      step = "open the first beta tree";
      const link = page.locator('a[href*="/platform/decision-trees-beta/"]').first();
      await link.waitFor({ timeout: 30000 });
      log(`opening ${await link.getAttribute("href")}`);
      await link.click();
    }

    step = "designer loads";
    await page.getByRole("radio", { name: "Canvas" }).waitFor({ timeout: 45000 });
    const tabs = (await page.getByRole("radio").allInnerTexts()).map((t) => t.trim());
    log(`tabs: ${tabs.join(" | ")}`);
    const missingTabs = TABS.filter((t) => !tabs.includes(t));
    if (missingTabs.length) return fail(`missing tabs: ${missingTabs.join(", ")}`);

    step = "Targeting tab";
    await page.getByRole("radio", { name: "Targeting" }).click();
    await page.getByText("Where this tree runs").waitFor({ timeout: 15000 });
    if ((await page.getByRole("radio", { name: "Targeting" }).getAttribute("aria-checked")) !== "true") {
      return fail("Targeting tab did not become the selected tab");
    }
    if ((await page.getByRole("button", { name: "Add" }).count()) === 0) {
      return fail("crop picker (Add button) not shown");
    }

    step = "countries load";
    // The country list is fetched after the tab renders; wait for it rather
    // than reading an empty list as "no countries".
    const soilNames = new Set(SOILS);
    const countryBoxes = async () => {
      const labels = await page.locator('label:has(input[type="checkbox"])').allInnerTexts();
      return labels.map((l) => l.trim()).filter((l) => l && !soilNames.has(l));
    };
    const deadline = Date.now() + 20000;
    let countries = await countryBoxes();
    while (countries.length === 0 && Date.now() < deadline) {
      await page.waitForTimeout(500);
      countries = await countryBoxes();
    }
    if (countries.length === 0) return fail("no country checkboxes after 20 s");
    log(`countries: ${countries.length}`);

    step = "soil textures";
    for (const s of SOILS) {
      if ((await page.getByLabel(s, { exact: true }).count()) === 0) return fail(`soil "${s}" missing`);
    }

    const shot = path.join(outDir, "beta-designer-targeting.png");
    await page.screenshot({ path: shot, fullPage: true });
    console.log(`OK: Beta designer and Targeting tab work in prod (screenshot: ${shot})`);
    await browser.close();
  } catch (e) {
    await fail(e.message.split("\n")[0]);
  }
})();
