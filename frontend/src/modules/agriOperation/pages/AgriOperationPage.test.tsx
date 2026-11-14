// The Catalog tab against mocked API calls: the farm's manuals load, the first
// one opens, its stages and activities render in week order, and an activity
// expands to its product, source and evidence.
/* eslint-disable @typescript-eslint/require-await */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { AgriOperationPage } from "./AgriOperationPage";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const api = vi.hoisted(() => ({
  listManualCatalog: vi.fn(),
  getFarmManual: vi.fn(),
}));
vi.mock("@/api/agriOperation", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listManualCatalog: api.listManualCatalog,
  getFarmManual: api.getFarmManual,
}));
vi.mock("@/api/crops", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listCrops: vi.fn(async () => [{ code: "mango", name_en: "Mango", name_ar: "مانجو" }]),
}));

const summary = {
  id: "t-keitt",
  code: "mango-keitt-eg",
  name: "Mango — Keitt (Egypt)",
  name_ar: null,
  crop_path: "mango.keitt",
  crop_id: null,
  country: "EG",
  region: null,
  description: "Late-season cultivar.",
  description_ar: null,
  status: "published",
  revision: 1,
  published_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  activity_count: 2,
};

const stages = [
  {
    code: "pre_flowering",
    name_en: "Pre-flowering",
    advance: { mode: "calendar_doy", start_doy: "12-01", end_doy: "01-31" },
  },
  {
    code: "flowering",
    name_en: "Flowering",
    advance: { mode: "calendar_doy", start_doy: "02-01", end_doy: "03-15" },
  },
];

const manual = {
  ...summary,
  milestones: [],
  is_perennial: true,
  stages,
  varieties: [{ path: "mango.keitt", name_en: "Keitt", name_ar: null, is_perennial: true, stages }],
  activities: [
    {
      id: "a2",
      code: "spraying-1",
      activity_type: "spraying",
      title: "Spray against mango leafhopper",
      anchor: "stage",
      stage_code: "flowering",
      offset_days: 7,
      duration_days: 1,
      milestone_id: null,
      product_name: "Imidacloprid",
      dosage: "per label",
      notes: "Hopper at flowering. [GENERIC] verify registration.",
      evidence_tier: "generic",
      source_tree_code: null,
      start_time: null,
      sort_order: 2,
    },
    {
      id: "a1",
      code: "growth_regulator-1",
      activity_type: "growth_regulator",
      title: "PBZ treatment for flowering induction",
      anchor: "stage",
      stage_code: "pre_flowering",
      offset_days: 0,
      duration_days: 1,
      milestone_id: null,
      product_name: "Paclobutrazol (PBZ)",
      dosage: null,
      notes: null,
      evidence_tier: "generic",
      source_tree_code: "t_flower_induction_readiness",
      start_time: null,
      sort_order: 1,
    },
  ],
};

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

describe("AgriOperationPage catalog", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    api.listManualCatalog.mockReset();
    api.getFarmManual.mockReset();
  });

  it("opens the first manual and lists its activities by stage", async () => {
    api.listManualCatalog.mockResolvedValue([summary]);
    api.getFarmManual.mockResolvedValue(manual);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Mango — Keitt (Egypt)" })).toBeTruthy();
    expect(api.getFarmManual).toHaveBeenCalledWith("f1", "t-keitt");
    expect(screen.getByText("52-week cycle · EG · 2 activities")).toBeTruthy();

    const pre = screen.getByRole("heading", { name: "Pre-flowering" }).closest("section")!;
    expect(within(pre).getByText("PBZ treatment for flowering induction")).toBeTruthy();
    expect(within(pre).getByText("Wk 1")).toBeTruthy();
    const flowering = screen.getByRole("heading", { name: "Flowering" }).closest("section")!;
    expect(within(flowering).getByText("Wk 10")).toBeTruthy();
    expect(within(flowering).getByText("Flowering +7 days")).toBeTruthy();

    // The stage filter narrows to one stage.
    fireEvent.click(screen.getByRole("button", { name: /Flowering/ }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Pre-flowering" })).toBeNull(),
    );
  });

  it("shows product, source and evidence, without the old note tags", async () => {
    api.listManualCatalog.mockResolvedValue([summary]);
    api.getFarmManual.mockResolvedValue(manual);
    renderPage();
    fireEvent.click(await screen.findByText("Spray against mango leafhopper"));
    expect(screen.getByText("Imidacloprid")).toBeTruthy();
    expect(screen.getByText("Hopper at flowering. verify registration.")).toBeTruthy();
    expect(screen.getAllByText("Generic data").length).toBeGreaterThan(0);
    expect(screen.getByText("Decision tree t_flower_induction_readiness")).toBeTruthy();
  });

  it("says so when no manual is published for the farm's crops", async () => {
    api.listManualCatalog.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No operation manual is published/)).toBeTruthy();
    expect(api.getFarmManual).not.toHaveBeenCalled();
  });
});
