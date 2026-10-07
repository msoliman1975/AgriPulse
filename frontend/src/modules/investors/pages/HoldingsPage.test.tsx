import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { HoldingsPage } from "./HoldingsPage";

const getFarmHoldingsMap = vi.fn();
const deleteHolding = vi.fn();

vi.mock("@/api/investors", () => ({
  getFarmHoldingsMap: (...a: unknown[]) => getFarmHoldingsMap(...a),
  deleteHolding: (...a: unknown[]) => deleteHolding(...a),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/prefs/PrefsContext", () => ({ usePrefs: () => ({ unit: "feddan" }) }));
// The map needs WebGL; the list is what this test is about.
vi.mock("../components/FarmHoldingsMap", () => ({ FarmHoldingsMap: () => null }));

function holding(id: string, code: string, history: boolean) {
  return {
    id,
    code,
    farm_id: "farm-1",
    block_id: "b1",
    block_code: "009",
    name: `Holding ${code}`,
    name_ar: null,
    area_m2: "1000",
    share_pct: "5",
    status: history ? "sold" : "available",
    tree_count: null,
    current_owner: null,
    has_ownership_history: history,
    archived_at: null,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/investments/holdings/farm-1"]}>
        <Routes>
          <Route path="/investments/holdings/:farmId" element={<HoldingsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<HoldingsPage> delete", () => {
  beforeEach(async () => {
    await setupTestI18n();
    getFarmHoldingsMap.mockReset();
    deleteHolding.mockReset();
    getFarmHoldingsMap.mockResolvedValue({
      farm_id: "farm-1",
      blocks: [],
      holdings: [holding("h-new", "H-0010", false), holding("h-sold", "H-0004", true)],
    });
    deleteHolding.mockResolvedValue(undefined);
  });

  it("offers Delete only on a holding with no ownership history", async () => {
    renderPage();
    const fresh = (await screen.findByText("H-0010")).closest("tr") as HTMLElement;
    const sold = screen.getByText("H-0004").closest("tr") as HTMLElement;
    expect(within(fresh).getByRole("button", { name: "Delete H-0010" })).toBeInTheDocument();
    expect(within(sold).queryByRole("button")).not.toBeInTheDocument();
  });

  it("deletes after the user confirms", async () => {
    renderPage();
    const fresh = (await screen.findByText("H-0010")).closest("tr") as HTMLElement;
    await userEvent.click(within(fresh).getByRole("button", { name: "Delete H-0010" }));
    expect(deleteHolding).not.toHaveBeenCalled();
    await userEvent.click(within(fresh).getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(deleteHolding).toHaveBeenCalledWith("farm-1", "h-new"));
  });
});
