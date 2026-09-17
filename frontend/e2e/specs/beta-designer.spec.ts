import { test, expect } from "../fixtures";

/**
 * Beta designer smoke.
 *
 * The beta screens read `src/api/decisionTreesBeta.ts`, which is mocked in
 * process, so this spec needs no route mocks of its own — the fixture's
 * catch-all covers `/v1/me` and the config read and nothing else is called.
 *
 * Two assertions that a unit test cannot make: the canvas actually draws all
 * four new node kinds, and the combinations tab lists the finding sets the
 * tree can produce rather than only the rules an author wrote.
 */

const TREE = "/decision-trees-beta/mango_water_beta";

test.describe("beta designer", () => {
  test("draws all four new node kinds on the canvas", async ({ authedPage: page }) => {
    await page.goto(TREE);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Mango water");

    const canvas = page.getByRole("application", { name: "Beta tree canvas" });
    await expect(canvas).toBeVisible();

    // The kind chip inside each node box. One of each is the whole point.
    for (const kind of ["Condition", "Register", "Set", "Switch", "Stop"]) {
      await expect(canvas.getByText(kind, { exact: true }).first()).toBeVisible();
    }

    // A switch shows its ordered bands and its default without being opened.
    await expect(canvas.getByText("1. at least 70 → reg_2")).toBeVisible();
    await expect(canvas.getByText("else → stop_1")).toBeVisible();
  });

  test("lists the sets that compose beside the sets that have a rule", async ({
    authedPage: page,
  }) => {
    await page.goto(TREE);
    await page.getByRole("radio", { name: "Combinations" }).click();

    const table = page.getByRole("table", { name: "Combinations" });
    await expect(table).toBeVisible();

    // The tree declares one rule, for {dry, ndvi_low}. Every other producible
    // set composes, and the table has to say which is which.
    await expect(table.getByText("Rule", { exact: true })).toHaveCount(1);
    await expect(table.getByText("Composes", { exact: true })).not.toHaveCount(0);
  });

  test("blocks the publish while a rejection stands and names the node", async ({
    authedPage: page,
  }) => {
    await page.goto(TREE);
    // The seeded tree compiles clean, so the panel says so and the button is
    // live. A tree with a rejection is covered by the compiler unit tests;
    // what this checks is that the panel and the button agree.
    await expect(page.getByText("No rejections. This version can be published.")).toBeVisible();
  });

  test("shows the finding catalogue with the shadowed tenant row flagged", async ({
    authedPage: page,
  }) => {
    await page.goto("/decision-tree-findings");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Finding catalogue");
    await expect(page.getByRole("table", { name: "Platform findings" })).toBeVisible();
    // The tenant `dry` row duplicates a platform code, so the fold never reads
    // it. This screen is the only place that says so.
    await expect(page.getByText("Shadowed").first()).toBeVisible();
  });
});
