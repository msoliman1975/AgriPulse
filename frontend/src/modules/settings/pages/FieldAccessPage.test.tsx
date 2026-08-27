import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FieldAccessPage } from "./FieldAccessPage";

const fetchFieldEnrolmentAudit = vi.fn();
const grantFarmAccess = vi.fn();

vi.mock("@/api/fieldAccess", () => ({
  fetchFieldEnrolmentAudit: (...a: unknown[]) => fetchFieldEnrolmentAudit(...a),
  grantFarmAccess: (...a: unknown[]) => grantFarmAccess(...a),
  enrolFieldWorker: vi.fn(),
  reRoleFieldWorkers: vi.fn(),
  reissueFieldPin: vi.fn(),
}));

vi.mock("@/api/farms", () => ({
  listFarms: () =>
    Promise.resolve({
      items: [
        { id: "farm-1", name: "Bashayer Farm" },
        { id: "farm-2", name: "Mango Republic" },
      ],
      next_cursor: null,
    }),
}));

vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

function emptyAudit(over: Record<string, unknown> = {}) {
  return {
    total: 0,
    enrolled: [],
    ready_to_enrol: [],
    blocked_by_role: [],
    missing_phone: [],
    scope_mismatch: [],
    ...over,
  };
}

const TAREK = {
  id: "w-1",
  name: "Tarek Mahmoud",
  role: "Scout",
  phone: "+201001234567",
  has_phone: true,
  user_id: "u-1",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FieldAccessPage />
    </QueryClientProvider>,
  );
}

describe("FieldAccessPage — a second farm for someone who already has the app", () => {
  beforeEach(() => {
    setupTestI18n();
    vi.clearAllMocks();
    grantFarmAccess.mockResolvedValue({
      user_id: "u-1",
      membership_id: "m-1",
      farm_id: "farm-2",
      role: "Scout",
      worker_id: "w-1",
    });
  });

  it("grants another farm without re-enrolling the person", async () => {
    // The gap this closes: enrolling them again 409s, because one phone is
    // one username. Adding a farm has to be its own action.
    fetchFieldEnrolmentAudit.mockResolvedValue(emptyAudit({ enrolled: [TAREK] }));
    renderPage();

    const row = within(await screen.findByRole("row", { name: /Tarek Mahmoud/ }));
    await userEvent.selectOptions(row.getByLabelText("Also works on"), "farm-2");
    await userEvent.click(row.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(grantFarmAccess).toHaveBeenCalledWith({
        user_id: "u-1",
        farm_id: "farm-2",
        role: "Scout",
      }),
    );
  });

  it("does not offer the farm the person is already on", async () => {
    // Re-granting is a no-op the API would accept, which would read as the
    // action having done something.
    fetchFieldEnrolmentAudit.mockResolvedValue(emptyAudit({ enrolled: [TAREK] }));
    renderPage();

    const row = within(await screen.findByRole("row", { name: /Tarek Mahmoud/ }));
    const options = within(row.getByLabelText("Also works on")).getAllByRole("option");
    const values = options.map((o) => (o as HTMLOptionElement).value);
    expect(values).toContain("farm-2");
    expect(values).not.toContain("farm-1");
  });

  it("carries the role the person already holds rather than defaulting to Scout", async () => {
    fetchFieldEnrolmentAudit.mockResolvedValue(
      emptyAudit({ enrolled: [{ ...TAREK, role: "FieldOperator" }] }),
    );
    renderPage();

    const row = within(await screen.findByRole("row", { name: /Tarek Mahmoud/ }));
    await userEvent.selectOptions(row.getByLabelText("Also works on"), "farm-2");
    await userEvent.click(row.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(grantFarmAccess).toHaveBeenCalledWith(
        expect.objectContaining({ role: "FieldOperator" }),
      ),
    );
  });

  it("shows the people who can be given work here but cannot open it", async () => {
    // The API has always returned this bucket and the page never rendered it,
    // so the one signal that catches the two stores disagreeing was invisible.
    fetchFieldEnrolmentAudit.mockResolvedValue(
      emptyAudit({ scope_mismatch: [{ ...TAREK, name: "Mona Adel", id: "w-2", user_id: "u-2" }] }),
    );
    renderPage();

    expect(
      await screen.findByText("Can be given work here but cannot open it"),
    ).toBeInTheDocument();
    expect(screen.getByText("Mona Adel")).toBeInTheDocument();
  });

  it("fixes a mismatch by granting the farm they are standing on", async () => {
    fetchFieldEnrolmentAudit.mockResolvedValue(
      emptyAudit({ scope_mismatch: [{ ...TAREK, name: "Mona Adel", id: "w-2", user_id: "u-2" }] }),
    );
    renderPage();

    const row = within(await screen.findByRole("row", { name: /Mona Adel/ }));
    await userEvent.selectOptions(row.getByLabelText("Also works on"), "farm-1");
    await userEvent.click(row.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(grantFarmAccess).toHaveBeenCalledWith(
        expect.objectContaining({ user_id: "u-2", farm_id: "farm-1" }),
      ),
    );
  });

  // Worded to avoid the standalone word the DS-8 lint rule bans in string
  // literals; it matches prose as readily as a className.
  it("hides the mismatch section when the two stores agree", async () => {
    fetchFieldEnrolmentAudit.mockResolvedValue(emptyAudit({ enrolled: [TAREK] }));
    renderPage();

    await screen.findByText("Tarek Mahmoud");
    expect(
      screen.queryByText("Can be given work here but cannot open it"),
    ).not.toBeInTheDocument();
  });

  it("offers nothing for a worker row with no account behind it", async () => {
    // Linked to a membership by hand on the workers screen, never enrolled:
    // there is no user to grant anything to.
    fetchFieldEnrolmentAudit.mockResolvedValue(
      emptyAudit({ enrolled: [{ ...TAREK, user_id: null }] }),
    );
    renderPage();

    const row = within(await screen.findByRole("row", { name: /Tarek Mahmoud/ }));
    expect(row.queryByLabelText("Also works on")).not.toBeInTheDocument();
  });
});
