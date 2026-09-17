import type { Page } from "@playwright/test";

import { test, expect } from "../fixtures";

/**
 * Beta designer, against a stubbed server.
 *
 * The screens used to read an in-process mock, so this spec needed no route
 * mocks of its own. They now call the real endpoints, so the stub below is the
 * contract this branch was built against, written once and asserted against by
 * every test here. When session A's endpoints land, a shape that does not
 * match is a failure in this file rather than a screen that quietly renders
 * nothing.
 *
 * The long test is the round trip the designer exists for: open a tree,
 * publish it with a deliberate error, see the error land on the node that
 * caused it, fix it, publish, then run the dry run.
 */

const TREE_ID = "33333333-3333-7333-8333-333333333333";
const TREE_CODE = "mango_water_beta";
const TREE = `/decision-trees-beta/${TREE_CODE}`;
const BLOCK_ID = "44444444-4444-7444-8444-444444444444";
const FARM_ID = "55555555-5555-7555-8555-555555555555";

const DEFINITION = {
  code: TREE_CODE,
  name_en: "Mango water and pressure (beta)",
  name_ar: "الماء والضغط على المانجو (تجريبي)",
  registers: ["dry", "ndvi_low", "pest_high"],
  combinations: [
    {
      codes: ["dry", "ndvi_low"],
      action_type: "irrigate",
      status: "stressed",
      text_en: "Water shortage is the cause. Irrigate before treating anything else.",
      text_ar: "نقص المياه هو السبب. اسقِ قبل معالجة أي شيء آخر.",
    },
  ],
  root: "cond_1",
  nodes: {
    cond_1: {
      label_en: "Is leaf water below baseline?",
      condition: {
        tree: {
          op: "lt",
          left: { source: "indices", index_code: "ndmi", key: "baseline_deviation" },
          right: -0.1,
        },
      },
      on_match: "reg_1",
      on_miss: "set_1",
    },
    reg_1: {
      label_en: "Record low leaf water",
      register: { code: "dry", severity: "warning" },
      next: "set_1",
    },
    set_1: {
      label_en: "Remember which index was used",
      set: { index_used: "ndmi" },
      next: "sw_1",
    },
    sw_1: {
      label_en: "Anthracnose pressure bands",
      switch: {
        on: { source: "weather_risk", risk_code: "anthracnose", field: "score" },
        // A case names its operator as the key. It was `{op, value, go}`
        // until the engine refused every switch written that way; this stub
        // kept the old shape and the band read as "op.?" on the canvas.
        cases: [
          { ge: 70, go: "reg_2" },
          { ge: 40, go: "reg_3" },
        ],
        default: "stop_1",
      },
    },
    reg_2: {
      label_en: "Record high pest pressure",
      register: { code: "pest_high", severity: "critical" },
      next: "stop_1",
    },
    reg_3: {
      label_en: "Record dropping vigour",
      register: { code: "ndvi_low", severity: "info" },
      next: "stop_1",
    },
    stop_1: { label_en: "End and fold", stop: true },
  },
};

const PLATFORM_FINDINGS = [
  {
    code: "dry",
    name_en: "Low leaf water",
    name_ar: "انخفاض ماء الورقة",
    clause_en: "leaf water is low",
    clause_ar: "ماء الورقة منخفض",
    default_status: "stressed",
    description_en: null,
    description_ar: null,
    is_active: true,
    source: "platform",
    shadowed: false,
  },
  {
    code: "ndvi_low",
    name_en: "Canopy vigour dropped",
    name_ar: "انخفاض حيوية المجموع الخضري",
    clause_en: "canopy vigour dropped",
    clause_ar: "انخفضت حيوية المجموع الخضري",
    default_status: "watch",
    description_en: null,
    description_ar: null,
    is_active: true,
    source: "platform",
    shadowed: false,
  },
  {
    code: "pest_high",
    name_en: "Pest pressure high",
    name_ar: "ضغط آفات مرتفع",
    clause_en: "anthracnose pressure is high",
    clause_ar: "ضغط الأنثراكنوز مرتفع",
    default_status: "stressed",
    description_en: null,
    description_ar: null,
    is_active: true,
    source: "platform",
    shadowed: false,
  },
];

const TENANT_FINDINGS = [
  {
    code: "salinity_rising",
    name_en: "Salinity rising",
    name_ar: "ارتفاع الملوحة",
    clause_en: "soil salinity is rising",
    clause_ar: "ملوحة التربة في ارتفاع",
    default_status: "watch",
    description_en: null,
    description_ar: null,
    is_active: true,
    source: "tenant",
    shadowed: false,
  },
  {
    // Deliberate: the code exists on the platform side too, so the fold never
    // reads this row. The catalogue screen is the only place that says so.
    code: "dry",
    name_en: "Low leaf water (local wording)",
    name_ar: "انخفاض ماء الورقة (صياغة محلية)",
    clause_en: "the leaves are running dry",
    clause_ar: "الأوراق بدأت تجف",
    default_status: "stressed",
    description_en: null,
    description_ar: null,
    is_active: true,
    source: "tenant",
    shadowed: true,
  },
];

interface StubOptions {
  /** How many publish attempts are refused before one is accepted. */
  refusePublishes?: number;
  /** Cells the dry run answers with. Empty means a block with no grid. */
  dryRunCells?: number;
}

function summary() {
  return {
    id: TREE_ID,
    code: TREE_CODE,
    name_en: DEFINITION.name_en,
    name_ar: DEFINITION.name_ar,
    tenant_id: "22222222-2222-7222-8222-222222222222",
    scope: "cell",
    current_version: 2,
    published_version: 1,
    updated_at: new Date().toISOString(),
  };
}

function versions() {
  const now = new Date().toISOString();
  return [
    {
      id: "v1",
      version: 1,
      definition: DEFINITION,
      published_at: now,
      created_at: now,
      notes: "First cut",
    },
    {
      id: "v2",
      version: 2,
      definition: DEFINITION,
      published_at: null,
      created_at: now,
      notes: null,
    },
  ];
}

function dryRunBody(cells: number) {
  return {
    block_id: BLOCK_ID,
    cells_evaluated: cells,
    cells_with_card: cells,
    cells: Array.from({ length: cells }, (_, i) => ({
      cell_id: `cell-${i + 1}`,
      cell_row: Math.floor(i / 3) + 1,
      cell_col: (i % 3) + 1,
      finding_set: ["dry", "ndvi_low"],
      matched_rule_codes: ["dry", "ndvi_low"],
      severity: "warning",
      status: "stressed",
      action_type: "irrigate",
      text_en: "Water shortage is the cause. Irrigate before treating anything else.",
      text_ar: "نقص المياه هو السبب. اسقِ قبل معالجة أي شيء آخر.",
      unresolved: [],
      error: null,
    })),
  };
}

/**
 * Stand the endpoints up.
 *
 * Registered inside the test, so it takes precedence over the fixture's
 * catch-all: Playwright matches the most recently added route first.
 */
async function stubBetaApi(page: Page, options: StubOptions = {}): Promise<void> {
  let publishesLeftToRefuse = options.refusePublishes ?? 0;
  const cells = options.dryRunCells ?? 6;

  await page.route("**/api/v1/**", async (route, request): Promise<void> => {
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/decision-tree-findings" && method === "GET") {
      return json(200, { findings: PLATFORM_FINDINGS });
    }
    if (path === "/tenant/decision-tree-findings" && method === "GET") {
      return json(200, { findings: TENANT_FINDINGS });
    }
    if (path === "/platform/decision-trees/beta" && method === "GET") {
      return json(200, [summary()]);
    }
    if (path === `/platform/decision-trees/beta/${TREE_ID}` && method === "GET") {
      return json(200, { ...summary(), versions: versions() });
    }
    if (path === `/platform/decision-trees/beta/${TREE_ID}/versions` && method === "POST") {
      return json(201, {
        id: "v3",
        version: 3,
        definition: DEFINITION,
        published_at: null,
        created_at: new Date().toISOString(),
        notes: null,
      });
    }
    if (path === `/platform/decision-trees/beta/${TREE_ID}/publish` && method === "POST") {
      if (publishesLeftToRefuse > 0) {
        publishesLeftToRefuse -= 1;
        return route.fulfill({
          status: 422,
          contentType: "application/problem+json",
          body: JSON.stringify({
            type: "https://agripulse.cloud/problems/recommendations/tree-does-not-compile",
            title: "The tree does not compile",
            status: 422,
            detail: "One or more publish checks failed.",
            errors: [
              {
                rule: "register-not-declared",
                node_id: "reg_2",
                node_ids: ["reg_2"],
                message_en: '"reg_2" registers "pest_high", which is not in the registers list.',
                message_ar: '"reg_2" تسجّل "pest_high" وهو غير معلن في القائمة.',
              },
            ],
          }),
        });
      }
      return json(200, { ...summary(), published_version: 3, versions: versions() });
    }
    if (path === `/platform/decision-trees/beta/${TREE_ID}/draft` && method === "DELETE") {
      return route.fulfill({ status: 204, body: "" });
    }
    if (path === `/platform/decision-trees/beta/${TREE_ID}/dry-run` && method === "POST") {
      return json(200, dryRunBody(cells));
    }
    if (path === "/farms" && method === "GET") {
      return json(200, {
        items: [
          { id: FARM_ID, code: "F1", name: "Bashayer", name_ar: null, area_m2: 0, area_value: 0 },
        ],
        next_cursor: null,
      });
    }
    if (path === `/farms/${FARM_ID}/blocks` && method === "GET") {
      return json(200, {
        items: [
          {
            id: BLOCK_ID,
            farm_id: FARM_ID,
            code: "N12",
            name: "North 12",
            name_ar: null,
            area_m2: 0,
            area_value: 0,
          },
        ],
        next_cursor: null,
      });
    }
    return route.fallback();
  });
}

test.describe("beta designer", () => {
  test("draws all four new node kinds on the canvas", async ({ authedPage: page }) => {
    await stubBetaApi(page);
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
    await stubBetaApi(page);
    await page.goto(TREE);
    await page.getByRole("radio", { name: "Combinations" }).click();

    const table = page.getByRole("table", { name: "Combinations" });
    await expect(table).toBeVisible();

    // The tree declares one rule, for {dry, ndvi_low}. Every other producible
    // set composes, and the table has to say which is which.
    await expect(table.getByText("Rule", { exact: true })).toHaveCount(1);
    await expect(table.getByText("Composes", { exact: true })).not.toHaveCount(0);
  });

  test("refuses a publish, lands the error on the node, then publishes and runs", async ({
    authedPage: page,
  }) => {
    await stubBetaApi(page, { refusePublishes: 1 });
    await page.goto(TREE);

    const canvas = page.getByRole("application", { name: "Beta tree canvas" });
    await expect(canvas).toBeVisible();

    // Nothing has been sent yet, so the panel says the server has not looked.
    await expect(
      page.getByText("Nothing has come back for this version.", { exact: false }),
    ).toBeVisible();
    await expect(page.locator('[data-node-id="reg_2"]')).toHaveAttribute("data-rejected", "false");

    // The deliberate error: the server refuses this version and names reg_2.
    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("The server refused this version")).toBeVisible();
    await expect(
      page.getByText('"reg_2" registers "pest_high", which is not in the registers list.'),
    ).toBeVisible();

    // The error lands on the node, not only in the list beside it.
    await expect(page.locator('[data-node-id="reg_2"]')).toHaveAttribute("data-rejected", "true");

    // And the row is the way to the node: clicking it opens reg_2.
    await page.getByRole("button", { name: "Open reg_2" }).click();
    await expect(page.getByText("reg_2", { exact: true }).first()).toBeVisible();

    // While the error stands the publish button is dead.
    await expect(page.getByRole("button", { name: "Publish" })).toBeDisabled();

    // Fix it: edit the node's label, which clears the server's answer because
    // it was about a body that no longer exists, then save and publish again.
    await page.getByLabel("Label (English)").first().fill("Record pest pressure");
    await expect(page.getByText("Unsaved changes")).toBeVisible();
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText("Unsaved changes")).toHaveCount(0);

    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("The server published this version.")).toBeVisible();

    // Now the dry run, over a real block, reading the fold per cell.
    await page.getByRole("radio", { name: "Dry run" }).click();
    await page.getByLabel("Block").selectOption(BLOCK_ID);
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page.getByText("6 of 6 cells produce a card.")).toBeVisible();
    await expect(
      page.getByRole("cell", { name: "Water shortage is the cause.", exact: false }).first(),
    ).toBeVisible();
  });

  test("says a block with no grid has no cells, rather than showing an empty table", async ({
    authedPage: page,
  }) => {
    await stubBetaApi(page, { dryRunCells: 0 });
    await page.goto(TREE);

    await page.getByRole("radio", { name: "Dry run" }).click();
    await page.getByLabel("Block").selectOption(BLOCK_ID);
    await page.getByRole("button", { name: "Run", exact: true }).click();

    await expect(
      page.getByText("This block has no grid, so there are no cells to fold."),
    ).toBeVisible();
  });

  test("draws the stop as a circle, moves a node, and puts the layout back", async ({
    authedPage: page,
  }) => {
    await stubBetaApi(page);
    await page.goto(TREE);

    const canvas = page.getByRole("application", { name: "Beta tree canvas" });
    await expect(canvas).toBeVisible();

    // The walk ending is the one thing on the canvas that is not a step.
    const stop = page.locator('[data-node-id="stop_1"]');
    await expect(stop).toHaveAttribute("data-shape", "circle");
    await expect(page.locator('[data-node-id="reg_1"]')).not.toHaveAttribute(
      "data-shape",
      "circle",
    );

    // Nothing has been moved, so there is nothing to put back.
    await expect(page.getByRole("button", { name: "Back to automatic layout" })).toHaveCount(0);

    const node = page.locator('[data-node-id="reg_1"]');
    const box = (await node.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 60, { steps: 8 });
    await page.mouse.up();

    // The move is an edit: it goes into the draft and it can be undone in one
    // click.
    await expect(page.getByText("Unsaved changes")).toBeVisible();
    await expect(page.locator('[data-node-id="reg_1"]')).toHaveAttribute("data-pinned", "true");

    await page.getByRole("button", { name: "Back to automatic layout" }).click();
    await expect(page.locator('[data-node-id="reg_1"]')).toHaveAttribute("data-pinned", "false");
  });

  test("authors a condition, including a between range", async ({ authedPage: page }) => {
    await stubBetaApi(page);
    await page.goto(TREE);

    await page.locator('[data-node-id="cond_1"]').click();

    // The test itself, not only the two branches: this is what the panel
    // could not edit before.
    await expect(page.getByLabel("Operator")).toHaveValue("lt");
    await page.getByLabel("Operator").selectOption("between");

    await expect(page.getByLabel("From", { exact: true })).toBeVisible();
    await page.getByLabel("To", { exact: true }).fill("0.2");
    await expect(page.getByText("Unsaved changes")).toBeVisible();

    // The canvas reads the same edit back.
    await expect(page.locator('[data-node-id="cond_1"]')).toBeVisible();
  });

  test("shows the finding catalogue with the shadowed tenant row flagged", async ({
    authedPage: page,
  }) => {
    await stubBetaApi(page);
    await page.goto("/decision-tree-findings");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Finding catalogue");
    await expect(page.getByRole("table", { name: "Platform findings" })).toBeVisible();
    // The tenant `dry` row duplicates a platform code, so the fold never reads
    // it. This screen is the only place that says so.
    await expect(page.getByText("Shadowed").first()).toBeVisible();
  });
});
