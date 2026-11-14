// The platform manual editor against mocked API calls: a manual loads laid out
// by stage, an edit enables Save and saves the whole tree, and Publish shows
// the impact before publishing.
/* eslint-disable @typescript-eslint/require-await */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { ManualEditorPage } from "./ManualEditorPage";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const api = vi.hoisted(() => ({
  getPlanTemplate: vi.fn(),
  updatePlanTemplate: vi.fn(),
  publishPlanTemplate: vi.fn(),
  resolveTemplatePhenology: vi.fn(),
  getAuthoringManual: vi.fn(),
  getPublishImpact: vi.fn(),
}));
vi.mock("@/api/planTemplates", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getPlanTemplate: api.getPlanTemplate,
  updatePlanTemplate: api.updatePlanTemplate,
  publishPlanTemplate: api.publishPlanTemplate,
  resolveTemplatePhenology: api.resolveTemplatePhenology,
}));
vi.mock("@/api/agriOperation", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getAuthoringManual: api.getAuthoringManual,
  getPublishImpact: api.getPublishImpact,
}));
vi.mock("@/api/inputs", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listInputs: vi.fn(async () => []),
}));
vi.mock("@/api/cropCatalog", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listAdminCrops: vi.fn(async () => []),
  listAdminStrains: vi.fn(async () => []),
  listAdminVarieties: vi.fn(async () => []),
}));

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

const detail = {
  id: "t1",
  code: "mango-keitt-eg",
  name: "Mango — Keitt (Egypt)",
  name_ar: null,
  crop_path: "mango.keitt",
  crop_id: null,
  country: "EG",
  region: null,
  description: null,
  description_ar: null,
  status: "published",
  revision: 1,
  published_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  activity_count: 1,
  milestones: [],
  activities: [
    {
      id: "a1",
      code: "spraying-1",
      activity_type: "spraying",
      title: "Spray against mango leafhopper",
      title_ar: null,
      anchor: "stage",
      stage_code: "flowering",
      milestone_id: null,
      offset_days: 7,
      duration_days: 1,
      product_name: "Imidacloprid",
      dosage: "per label",
      notes: null,
      evidence_tier: "generic",
      source_tree_code: null,
      start_time: null,
      sort_order: 0,
    },
  ],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/platform/operation-manuals/t1"]}>
        <Routes>
          <Route path="/platform/operation-manuals/:id" element={<ManualEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ManualEditorPage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    Object.values(api).forEach((f) => f.mockReset());
    api.getPlanTemplate.mockResolvedValue(detail);
    api.resolveTemplatePhenology.mockResolvedValue({
      crop_path: "mango.keitt",
      is_perennial: true,
      stages,
    });
    api.getAuthoringManual.mockResolvedValue({
      ...detail,
      is_perennial: true,
      stages,
      varieties: [
        { path: "mango.keitt", name_en: "Keitt", name_ar: null, is_perennial: true, stages },
      ],
    });
  });

  it("lays the manual out by stage and saves an edit", async () => {
    api.updatePlanTemplate.mockImplementation(async (_id: string, body: { name: string }) => ({
      ...detail,
      name: body.name,
    }));
    renderPage();

    const flowering = (await screen.findByRole("heading", { name: "Flowering" })).closest(
      "section",
    )!;
    expect(within(flowering).getByText("Spray against mango leafhopper")).toBeTruthy();
    const pre = screen.getByRole("heading", { name: "Pre-flowering" }).closest("section")!;
    expect(within(pre).getByText("No activities in this stage.")).toBeTruthy();

    const save = screen.getByRole("button", { name: "Save draft" });
    expect(save).toHaveProperty("disabled", true);
    fireEvent.change(within(flowering).getByLabelText("Product"), {
      target: { value: "Acetamiprid" },
    });
    expect(screen.getByText("You have unsaved changes.")).toBeTruthy();
    fireEvent.click(save);

    await waitFor(() => expect(api.updatePlanTemplate).toHaveBeenCalled());
    const [id, body] = api.updatePlanTemplate.mock.calls[0] as [string, { activities: object[] }];
    expect(id).toBe("t1");
    expect(body.activities[0]).toMatchObject({
      code: "spraying-1",
      product_name: "Acetamiprid",
      stage_code: "flowering",
      offset_days: 7,
    });
  });

  it("shows the publish impact before publishing", async () => {
    api.getPublishImpact.mockResolvedValue({
      farms: 3,
      saved_plans: 4,
      comparable: true,
      added: [],
      removed: [],
      changed: [
        {
          code: "spraying-1",
          title: "Spray against mango leafhopper",
          title_ar: null,
          fields: ["dosage"],
        },
      ],
    });
    api.publishPlanTemplate.mockResolvedValue(detail);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Publish…" }));
    expect(await screen.findByText("Used by 3 farms in 4 saved plans.")).toBeTruthy();
    expect(screen.getByText("Changed: Spray against mango leafhopper (dosage)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.publishPlanTemplate).toHaveBeenCalledWith("t1"));
  });
});
