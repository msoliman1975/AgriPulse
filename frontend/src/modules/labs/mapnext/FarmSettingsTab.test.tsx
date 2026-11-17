import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FarmSettingsTab } from "./FarmSettingsTab";

// This tab is the ONLY place in either console where an existing farm can be
// renamed, so it is the only place an Arabic farm name can be added after
// creation. The column and every reader shipped before the field did, which
// is why these tests assert the patch that leaves the form, not the column.

const h = vi.hoisted(() => ({
  getFarm: vi.fn(),
  updateFarm: vi.fn(),
  listCountries: vi.fn(),
  previewFarmTreeImpact: vi.fn(),
}));

vi.mock("@/api/countries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/countries")>()),
  listCountries: h.listCountries,
}));

vi.mock("@/api/farmDecisionTrees", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/farmDecisionTrees")>()),
  previewFarmTreeImpact: h.previewFarmTreeImpact,
}));

vi.mock("@/api/farms", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/farms")>()),
  getFarm: h.getFarm,
  updateFarm: h.updateFarm,
}));

// Sections 2-4 write on their own and have their own tests; they would only
// add network mocks here.
vi.mock("./FarmSubscriptionsPanel", () => ({ FarmSubscriptionsPanel: () => null }));
vi.mock("./FarmZonesPanel", () => ({ FarmZonesPanel: () => null }));
vi.mock("./FarmHealthPanel", () => ({ FarmHealthPanel: () => null }));
vi.mock("./FarmDecisionTreesPanel", () => ({ FarmDecisionTreesPanel: () => null }));

function farm(over: Record<string, unknown> = {}) {
  return {
    id: "f1",
    code: "SUEZ-01",
    name: "Suez East",
    name_ar: null,
    description: null,
    description_ar: null,
    governorate: null,
    district: null,
    nearest_city: null,
    country_code: null,
    primary_water_source: null,
    tags: [],
    is_active: true,
    active_to: null,
    ...over,
  };
}

const COUNTRIES = [
  { id: "c1", code: "EG", name_en: "Egypt", name_ar: "مصر", is_active: true },
  { id: "c2", code: "SA", name_en: "Saudi Arabia", name_ar: "السعودية", is_active: true },
];

function impact(over: Record<string, unknown> = {}) {
  return {
    farm_id: "f1",
    has_crops_before: true,
    has_crops_after: true,
    blocks: [],
    farm_starting: [],
    farm_stopping: [],
    exclusions_cleared: [],
    changes_anything: false,
    ...over,
  };
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FarmSettingsTab
          farmId="f1"
          farmName="Suez East"
          canInactivate={false}
          onInactivateFarm={vi.fn()}
          onReactivateFarm={vi.fn()}
          reactivating={false}
          reactivateError={null}
          farmQueryKey={["farm", "f1"]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FarmSettingsTab — Arabic farm name", () => {
  beforeEach(() => {
    h.getFarm.mockReset();
    h.updateFarm.mockReset();
    h.updateFarm.mockResolvedValue(farm());
    h.listCountries.mockResolvedValue(COUNTRIES);
  });

  it("saves an Arabic name typed onto a farm that had none", async () => {
    await setupTestI18n("en");
    h.getFarm.mockResolvedValue(farm());
    renderTab();
    const user = userEvent.setup();

    const field = await screen.findByLabelText("Arabic name");
    await user.type(field, "السويس الشرقية");
    await user.click(screen.getByRole("button", { name: /Save farm details/i }));

    await waitFor(() => expect(h.updateFarm).toHaveBeenCalledTimes(1));
    expect(h.updateFarm).toHaveBeenCalledWith(
      "f1",
      expect.objectContaining({ name: "Suez East", name_ar: "السويس الشرقية" }),
    );
  });

  it("shows the Arabic name already stored, and clears it back to null", async () => {
    await setupTestI18n("en");
    h.getFarm.mockResolvedValue(farm({ name_ar: "السويس الشرقية" }));
    renderTab();
    const user = userEvent.setup();

    const field = await screen.findByLabelText("Arabic name");
    expect(field).toHaveValue("السويس الشرقية");

    // Blank means "no Arabic name", and the reader's COALESCE only falls back
    // on NULL or an empty string — so an emptied box must not send "".
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: /Save farm details/i }));

    await waitFor(() => expect(h.updateFarm).toHaveBeenCalledTimes(1));
    expect(h.updateFarm.mock.calls[0][1].name_ar).toBeNull();
  });
});

// Decision trees target farms by country, and this tab is where the consoles
// edit a farm — so the country has to be settable here, not only on the
// legacy /farms/:id/edit page.
describe("FarmSettingsTab — country", () => {
  beforeEach(() => {
    h.getFarm.mockReset();
    h.updateFarm.mockReset();
    h.listCountries.mockReset();
    h.previewFarmTreeImpact.mockReset();
    h.updateFarm.mockResolvedValue(farm());
    h.listCountries.mockResolvedValue(COUNTRIES);
  });

  it("shows the stored country and saves it untouched with no preview", async () => {
    await setupTestI18n("en");
    h.getFarm.mockResolvedValue(farm({ country_code: "EG" }));
    renderTab();
    const user = userEvent.setup();

    const select = await screen.findByLabelText("Country");
    await screen.findByRole("option", { name: "Egypt" });
    expect(select).toHaveValue("EG");

    await user.click(screen.getByRole("button", { name: /Save farm details/i }));
    await waitFor(() => expect(h.updateFarm).toHaveBeenCalledTimes(1));
    expect(h.updateFarm.mock.calls[0][1].country_code).toBe("EG");
    expect(h.previewFarmTreeImpact).not.toHaveBeenCalled();
  });

  it("sets a country on a farm that had none, previewing the tree impact first", async () => {
    await setupTestI18n("en");
    h.getFarm.mockResolvedValue(farm());
    h.previewFarmTreeImpact.mockResolvedValue(impact());
    renderTab();
    const user = userEvent.setup();

    await screen.findByRole("option", { name: "Egypt" });
    await user.selectOptions(screen.getByLabelText("Country"), "EG");
    await user.click(screen.getByRole("button", { name: /Save farm details/i }));

    await waitFor(() => expect(h.updateFarm).toHaveBeenCalledTimes(1));
    expect(h.previewFarmTreeImpact).toHaveBeenCalledWith("f1", { country_code: "EG" });
    expect(h.updateFarm.mock.calls[0][1].country_code).toBe("EG");
  });

  it("does not save when the tree-impact dialog is cancelled", async () => {
    await setupTestI18n("en");
    h.getFarm.mockResolvedValue(farm({ country_code: "EG" }));
    h.previewFarmTreeImpact.mockResolvedValue(
      impact({
        changes_anything: true,
        farm_stopping: [
          { tree_id: "t1", code: "palm", name_en: "Palm", name_ar: null, enabled: true },
        ],
      }),
    );
    renderTab();
    const user = userEvent.setup();

    await screen.findByRole("option", { name: "Saudi Arabia" });
    await user.selectOptions(screen.getByLabelText("Country"), "SA");
    await user.click(screen.getByRole("button", { name: /Save farm details/i }));

    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(h.updateFarm).not.toHaveBeenCalled();
  });
});
