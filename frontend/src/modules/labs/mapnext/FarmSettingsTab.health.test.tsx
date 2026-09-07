import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FarmSettingsTab } from "./FarmSettingsTab";

// Is the health panel REACHABLE? Not "does it render in isolation" — that is
// FarmHealthPanel.test.tsx — but "does the tab both consoles import actually
// mount it".
//
// This is the check the Arabic-names work did not have. The columns and every
// reader shipped, and there was nowhere in the product to type the value,
// because the two forms that ask for one were unreachable. Nothing failed.
//
// It is also the check the two-console drift did not have: farm subscriptions
// and the farm-level cell size were mounted in one console's drawer and not
// the other's for the whole life of both features.

const h = vi.hoisted(() => ({ getFarm: vi.fn(), getHealthTemplate: vi.fn() }));

vi.mock("@/api/farms", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/farms")>()),
  getFarm: h.getFarm,
  updateFarm: vi.fn(),
}));

vi.mock("@/api/farmConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/farmConfig")>()),
  getHealthTemplate: h.getHealthTemplate,
}));

// The other panels have their own tests; mocked here so this file needs no
// network stubs beyond the one it is about.
vi.mock("./FarmSubscriptionsPanel", () => ({ FarmSubscriptionsPanel: () => null }));
vi.mock("./FarmZonesPanel", () => ({ FarmZonesPanel: () => null }));

describe("FarmSettingsTab — the health panel is mounted", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.getFarm.mockReset();
    h.getHealthTemplate.mockReset();
    h.getFarm.mockResolvedValue({
      id: "f1",
      code: "SUEZ-01",
      name: "Suez East",
      name_ar: null,
      description: null,
      description_ar: null,
      governorate: null,
      district: null,
      nearest_city: null,
      primary_water_source: null,
      tags: [],
      is_active: true,
      active_to: null,
    });
    h.getHealthTemplate.mockResolvedValue({ definition: null, locked: false });
  });

  it("renders the health definition section", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
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

    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());
    // And it asked the server for this farm's override, so the panel is live
    // rather than an empty heading.
    expect(h.getHealthTemplate).toHaveBeenCalledWith("f1");
  });
});
