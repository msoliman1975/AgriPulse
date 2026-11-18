// The Beta designer links to the traces page as `?tree=<code>`. The page has
// to open on that tree: the server filters by code (so a busy run's page is
// that tree's rows), and the search box shows what it is filtered to.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeTracesPage } from "./DecisionTreeTracesPage";

const h = vi.hoisted(() => ({ listEvalRuns: vi.fn(), listEvalTraces: vi.fn() }));

vi.mock("@/api/decisionTrees", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/decisionTrees")>()),
  listEvalRuns: h.listEvalRuns,
  listEvalTraces: h.listEvalTraces,
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const RUN = {
  id: "run-1",
  kind: "scheduled",
  actor_user_id: null,
  started_at: "2026-11-17T22:00:00Z",
  finished_at: "2026-11-17T22:01:00Z",
  duration_ms: 60000,
  blocks_evaluated: 10,
  trees_evaluated: 5,
  trees_skipped: 1,
  recommendations_opened: 0,
};

function renderAt(route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <DecisionTreeTracesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DecisionTreeTracesPage ?tree=", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.listEvalRuns.mockReset();
    h.listEvalTraces.mockReset();
    h.listEvalRuns.mockResolvedValue([RUN]);
    h.listEvalTraces.mockResolvedValue([]);
  });

  it("asks the server for that tree's traces only", async () => {
    renderAt("/decision-tree-traces?tree=date_palm_medjool_canopy_diagnosis");
    await waitFor(() => expect(h.listEvalTraces).toHaveBeenCalled());
    expect(h.listEvalTraces.mock.calls[0][0]).toMatchObject({
      run_id: "run-1",
      tree_code: "date_palm_medjool_canopy_diagnosis",
    });
    expect(screen.getByDisplayValue("date_palm_medjool_canopy_diagnosis")).toBeInTheDocument();
  });

  it("asks for every tree without it", async () => {
    renderAt("/decision-tree-traces");
    await waitFor(() => expect(h.listEvalTraces).toHaveBeenCalled());
    expect(h.listEvalTraces.mock.calls[0][0].tree_code).toBeUndefined();
  });
});
