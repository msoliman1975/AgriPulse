// The Plan tab end to end against mocked API calls: pick a manual in the
// Catalog, build a plan through the four steps (a block, one activity left
// out, a date), move a bar on the calendar with the keyboard, apply. Then the
// saved-plans list: "manual updated" with its changes, and delete behind an
// inline confirm.
/* eslint-disable @typescript-eslint/require-await */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { AgriOperationPage } from "../pages/AgriOperationPage";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: () => false }));

const api = vi.hoisted(() => ({
  listManualCatalog: vi.fn(),
  getFarmManual: vi.fn(),
  listSavedPlans: vi.fn(),
  previewSavedPlan: vi.fn(),
  createSavedPlan: vi.fn(),
  deleteSavedPlan: vi.fn(),
  getManualChanges: vi.fn(),
}));
vi.mock("@/api/agriOperation", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
vi.mock("@/api/crops", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listCrops: vi.fn(async () => [{ code: "mango", name_en: "Mango", name_ar: "مانجو" }]),
}));
vi.mock("@/api/blocks", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listBlocks: vi.fn(async () => ({
    items: [
      { id: "b1", code: "N1", name: "Block N1", name_ar: null },
      { id: "b2", code: "S3", name: "Block S3", name_ar: null },
    ],
  })),
}));
vi.mock("@/api/planTemplates", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listAppliableTemplates: vi.fn(async () => [
    {
      id: "t-keitt",
      matching_blocks: [
        { block_id: "b1", block_code: "N1", crop_path: "mango.keitt", planting_date: "2019-03-01" },
      ],
    },
  ]),
}));

const stages = [
  {
    code: "flowering",
    name_en: "Flowering",
    advance: { mode: "calendar_doy", start_doy: "02-01", end_doy: "03-15" },
  },
];
const act = (id: string, code: string, title: string) => ({
  id,
  code,
  activity_type: "spraying",
  title,
  anchor: "stage",
  stage_code: "flowering",
  offset_days: 0,
  duration_days: 1,
  milestone_id: null,
  product_name: "Product",
  dosage: null,
  notes: null,
  start_time: null,
  sort_order: 1,
});
const manual = {
  id: "t-keitt",
  code: "mango-keitt-eg",
  name: "Mango — Keitt (Egypt)",
  name_ar: null,
  crop_path: "mango.keitt",
  status: "published",
  milestones: [],
  is_perennial: true,
  stages,
  varieties: [{ path: "mango.keitt", name_en: "Keitt", name_ar: null, is_perennial: true, stages }],
  activities: [act("a1", "spraying-1", "Spray A"), act("a2", "spraying-2", "Spray B")],
};
const catalogItem = { ...manual, activity_count: 2, revision: 1 };

const scheduled = (date: string, overridden = false) => ({
  template_id: "t-keitt",
  rejected_blocks: [],
  missing_codes: [],
  total_activities: 1,
  blocks: [
    {
      block_id: "b1",
      block_code: "N1",
      crop_path: "mango.keitt",
      start_date: "2026-11-05",
      skipped: [],
      activities: [
        {
          activity_key: "spraying-1",
          source: "template",
          template_activity_id: "a1",
          activity_type: "spraying",
          title: "Spray A",
          title_ar: null,
          scheduled_date: date,
          default_date: "2027-02-01",
          date_overridden: overridden,
          duration_days: 1,
          anchored_stage_code: "flowering",
          product_name: "Product",
          dosage: null,
          notes: null,
        },
      ],
    },
  ],
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/agri-operation/f1"]}>
        <Routes>
          <Route path="/agri-operation/:farmId" element={<AgriOperationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Plan tab", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    Object.values(api).forEach((f) => f.mockReset());
    api.listManualCatalog.mockResolvedValue([catalogItem]);
    api.getFarmManual.mockResolvedValue(manual);
  });

  it("builds and applies a plan through the four steps", async () => {
    api.listSavedPlans.mockResolvedValue([]);
    api.previewSavedPlan.mockImplementation(
      async (_farm: string, body: { date_overrides: Record<string, Record<string, string>> }) =>
        body.date_overrides.b1?.["spraying-1"]
          ? scheduled(body.date_overrides.b1["spraying-1"], true)
          : scheduled("2027-02-01"),
    );
    api.createSavedPlan.mockResolvedValue({
      allocation: { id: "p1", blocks: [{ block_id: "b1", start_date: "2026-11-05" }] },
      activities_created: 1,
      activities_kept: 0,
      skipped: 0,
    });
    renderPage();

    await screen.findByRole("heading", { name: "Mango — Keitt (Egypt)" });
    fireEvent.click(screen.getByRole("radio", { name: "Plan" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start a plan" }));

    // Step 1: the matching block is offered, the other one is not.
    fireEvent.click(await screen.findByRole("checkbox"));
    expect(screen.getByText("1 other blocks can't use this manual")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    // Step 2: leave Spray B out.
    fireEvent.click(await screen.findByRole("checkbox", { name: "Include Spray B" }));
    expect(screen.getByText(/1 of 2 manual activities included/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    // Step 3: the default date is enough.
    expect(await screen.findByText("Same start date for all blocks")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    // Step 4: move the bar one day with the keyboard; the preview re-runs with the override.
    const bar = await screen.findByRole("button", { name: /Spray A, 2027-02-01/ });
    fireEvent.keyDown(bar, { key: "ArrowRight" });
    await screen.findByRole("button", { name: /Spray A, 2027-02-02 \(moved\)/ });

    fireEvent.click(screen.getByRole("button", { name: "Apply to blocks" }));
    expect(await screen.findByText("Plan applied")).toBeTruthy();
    const body = api.createSavedPlan.mock.calls[0]?.[1];
    expect(body).toMatchObject({
      template_id: "t-keitt",
      blocks: [{ block_id: "b1" }],
      excluded_codes: ["spraying-2"],
      date_overrides: { b1: { "spraying-1": "2027-02-02" } },
    });
  });

  it("lists saved plans with manual updates and deletes after a confirm", async () => {
    api.listSavedPlans.mockResolvedValue([
      {
        id: "p1",
        template_id: "t-keitt",
        template_name: "Mango — Keitt (Egypt)",
        template_name_ar: null,
        template_code: "mango-keitt-eg",
        season_label: "Main season 2026",
        season_year: 2026,
        start_mode: "same",
        blocks: [{ block_id: "b1", start_date: "2026-11-05" }],
        excluded_codes: [],
        activity_edits: {},
        custom_activities: [],
        date_overrides: {},
        manual_updated: true,
        updated_at: "2026-11-10T00:00:00Z",
      },
    ]);
    api.getManualChanges.mockResolvedValue({
      comparable: true,
      added: [
        {
          code: "spraying-3",
          title: "Spray C",
          title_ar: null,
          activity_type: "spraying",
          fields: [],
        },
      ],
      removed: [],
      changed: [
        {
          code: "spraying-1",
          title: "Spray A",
          title_ar: null,
          activity_type: "spraying",
          fields: ["dosage"],
        },
      ],
    });
    api.deleteSavedPlan.mockResolvedValue(undefined);
    renderPage();
    await screen.findByRole("heading", { name: "Mango — Keitt (Egypt)" });
    fireEvent.click(screen.getByRole("radio", { name: "Plan" }));

    expect(await screen.findByText("Main season 2026")).toBeTruthy();
    expect(screen.getByText("Manual updated")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "What changed" }));
    expect(await screen.findByText("Added: Spray C")).toBeTruthy();
    expect(screen.getByText("Changed: Spray A (dosage)")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.deleteSavedPlan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete this plan" }));
    await waitFor(() => expect(api.deleteSavedPlan).toHaveBeenCalledWith("f1", "p1"));
  });
});
