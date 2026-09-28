/**
 * The platform engine switch: what it says before the click, and what it
 * sends.
 *
 * The response bodies copy the shape of `DecisionEngineResponse` in
 * `backend/app/modules/recommendations/schemas.py`, including the per-schema
 * `last_close_out.tenants` map the card sums.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { DecisionEngineState } from "@/api/decisionTreesBeta";

import { DecisionEngineSwitch } from "./DecisionEngineSwitch";

const getDecisionEngine = vi.fn();
const switchDecisionEngine = vi.fn();

vi.mock("@/api/decisionTreesBeta", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/decisionTreesBeta")>("@/api/decisionTreesBeta");
  return {
    ...actual,
    getDecisionEngine: () => getDecisionEngine(),
    switchDecisionEngine: (engine: string) => switchDecisionEngine(engine),
  };
});

const OLD: DecisionEngineState = {
  engine: "old",
  switched_at: null,
  switched_by: null,
  last_close_out: null,
};

const FLIPPED: DecisionEngineState = {
  engine: "beta",
  switched_at: "2026-09-24T10:00:00Z",
  switched_by: null,
  changed: true,
  last_close_out: {
    from: "old",
    to: "beta",
    tenants: {
      tenant_a: {
        recommendations_expired: 30,
        history_rows: 30,
        alerts_resolved: 4,
        verdicts_closed: 108,
      },
      tenant_b: {
        recommendations_expired: 2,
        history_rows: 2,
        alerts_resolved: 0,
        verdicts_closed: 12,
      },
    },
  },
};

function renderCard(published = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecisionEngineSwitch publishedBetaTrees={published} />
    </QueryClientProvider>,
  );
}

describe("DecisionEngineSwitch", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await setupTestI18n();
    getDecisionEngine.mockResolvedValue(OLD);
    switchDecisionEngine.mockResolvedValue(FLIPPED);
  });

  it("says which engine runs today", async () => {
    renderCard();
    expect(await screen.findByText("Old engine")).toBeInTheDocument();
    expect(
      screen.getByText("The sweep runs the old live trees. Published beta trees run nowhere."),
    ).toBeInTheDocument();
  });

  it("warns before the click and sends 'beta' only on confirm", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: "Switch to the beta engine" }));

    expect(screen.getByText("Switch every tenant to the beta engine?")).toBeInTheDocument();
    expect(screen.getByText("Published beta trees: 7.")).toBeInTheDocument();
    expect(switchDecisionEngine).not.toHaveBeenCalled();

    const buttons = screen.getAllByRole("button", { name: "Switch to the beta engine" });
    await user.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(switchDecisionEngine).toHaveBeenCalledWith("beta"));

    // The card sums the close-out across tenants: 30+2, 4+0, 108+12.
    expect(await screen.findByText("Beta engine")).toBeInTheDocument();
    expect(
      screen.getByText(/32 recommendations expired, 4 alerts resolved, 120 verdicts ended/),
    ).toBeInTheDocument();
  });

  it("warns that no tenant gets results when no beta tree is published", async () => {
    const user = userEvent.setup();
    renderCard(0);
    await user.click(await screen.findByRole("button", { name: "Switch to the beta engine" }));
    expect(
      screen.getByText(
        "No beta tree is published. After this switch, no tenant gets any decision-tree results.",
      ),
    ).toBeInTheDocument();
  });
});
