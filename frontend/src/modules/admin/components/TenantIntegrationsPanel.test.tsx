import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { TenantIntegrationsPanel } from "./TenantIntegrationsPanel";

// The decision-tree cadence is the first key here that takes one of a fixed
// set of numbers instead of a free value, and the choices come from the
// backend's own constraint. Two things must hold:
//
//   * the page offers exactly those numbers, so an admin cannot save a
//     cadence the hourly Beat tick could not honour;
//   * the list is read from the response and not from a copy in this file,
//     which is what would let the page drift from the write path.

const h = vi.hoisted(() => ({
  read: vi.fn(),
  write: vi.fn(),
  clear: vi.fn(),
}));

vi.mock("@/api/platformTenantIntegrations", () => ({
  readTenantIntegration: h.read,
  writeTenantIntegration: h.write,
  clearTenantIntegration: h.clear,
}));

const CADENCE_KEY = "recommendations.sweep_cadence_hours";

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TenantIntegrationsPanel tenantId="t1" />
    </QueryClientProvider>,
  );
}

describe("TenantIntegrationsPanel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
    h.read.mockImplementation((_tenantId: string, category: string) => {
      if (category !== "recommendations") return Promise.resolve({ settings: [] });
      return Promise.resolve({
        settings: [
          {
            key: CADENCE_KEY,
            value: 24,
            source: "platform",
            overridden_at: null,
            constraint: { numeric_choices: [4, 8, 24, 168], integer_only: true },
          },
        ],
      });
    });
    h.write.mockResolvedValue({
      key: CADENCE_KEY,
      value: 4,
      source: "tenant",
      overridden_at: null,
    });
  });

  it("offers the decision-tree cadence as the four values the backend accepts", async () => {
    renderPanel();
    const select = await screen.findByLabelText<HTMLSelectElement>(CADENCE_KEY);
    expect([...select.options].map((o) => o.value)).toEqual(["4", "8", "24", "168"]);
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Every 4 hours",
      "Every 8 hours",
      "Daily",
      "Weekly",
    ]);
    expect(select.value).toBe("24");
  });

  it("saves the chosen cadence as a number for that tenant", async () => {
    const user = userEvent.setup();
    renderPanel();
    const select = await screen.findByLabelText<HTMLSelectElement>(CADENCE_KEY);

    await user.selectOptions(select, "4");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() =>
      expect(h.write).toHaveBeenCalledWith("t1", "recommendations", CADENCE_KEY, 4),
    );
  });

  it("still renders a free text box for a key with no fixed choices", async () => {
    h.read.mockImplementation((_tenantId: string, category: string) =>
      Promise.resolve(
        category === "detection"
          ? {
              settings: [
                {
                  key: "grid.anomaly_z_threshold",
                  value: 1.5,
                  source: "platform",
                  overridden_at: null,
                  constraint: { minimum: 0.1, maximum: 10 },
                },
              ],
            }
          : { settings: [] },
      ),
    );
    renderPanel();
    const box = await screen.findByLabelText("grid.anomaly_z_threshold");
    expect(box.tagName).toBe("INPUT");
  });
});
