import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { InvestorsPage } from "./InvestorsPage";

const listInvestors = vi.fn();
const createInvestor = vi.fn();

vi.mock("@/api/investors", () => ({
  listInvestors: (...a: unknown[]) => listInvestors(...a),
  createInvestor: (...a: unknown[]) => createInvestor(...a),
}));

vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/prefs/PrefsContext", () => ({ usePrefs: () => ({ unit: "feddan" }) }));

const NOUR = {
  id: "inv-1",
  code: "INV-0001",
  investor_type: "person",
  full_name: "Nour Hassan",
  full_name_ar: "نور حسن",
  contact_person: null,
  email: "nour@example.com",
  phone: "+201000000001",
  national_id_type: null,
  national_id_last4: null,
  nationality: null,
  country: null,
  city: null,
  preferred_language: "ar",
  user_id: null,
  status: "not_invited",
  relationship_manager_id: null,
  notes_internal: null,
  invited_at: null,
  last_app_seen_at: null,
  archived_at: null,
  current_holdings_count: 2,
  current_area_m2: "16803.32",
  created_at: "2026-10-06T00:00:00Z",
  updated_at: "2026-10-06T00:00:00Z",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/settings/investors"]}>
        <Routes>
          <Route path="/settings/investors" element={<InvestorsPage />} />
          <Route path="/settings/investors/:id" element={<p>detail page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("InvestorsPage", () => {
  beforeEach(() => {
    setupTestI18n();
    vi.clearAllMocks();
  });

  it("lists investors with their holdings count", async () => {
    listInvestors.mockResolvedValue([NOUR]);
    renderPage();
    expect(await screen.findByText("INV-0001")).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Nour Hassan")).toBeInTheDocument();
    expect(table.getByText("Not invited")).toBeInTheDocument();
    expect(table.getByText("2")).toBeInTheDocument();
  });

  it("creates an investor and opens their page", async () => {
    listInvestors.mockResolvedValue([]);
    createInvestor.mockResolvedValue({ ...NOUR, id: "inv-9" });
    renderPage();
    const user = userEvent.setup();

    await user.click((await screen.findAllByRole("button", { name: "Add investor" }))[0]);
    await user.type(screen.getByLabelText("Full name (English)"), "Nour Hassan");
    await user.type(screen.getByLabelText("Email"), "nour@example.com");
    const dialog = screen.getByRole("dialog");
    await user.click(
      [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Add investor")!,
    );

    await waitFor(() => expect(createInvestor).toHaveBeenCalled());
    const payload = createInvestor.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.full_name).toBe("Nour Hassan");
    expect(payload.email).toBe("nour@example.com");
    expect(payload.preferred_language).toBe("ar");
    expect(payload.code).toBeNull();
    expect(await screen.findByText("detail page")).toBeInTheDocument();
  });
});
