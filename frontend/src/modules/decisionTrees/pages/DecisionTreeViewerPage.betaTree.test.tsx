// A beta tree opened through the old viewer goes to the beta designer.
//
// A beta (folding) tree's versions carry a JSON `definition` and no YAML, so
// the old viewer drew an empty canvas: "Tree has no nodes to display yet."
// The Medjool trees showed exactly that when reached by their code, for
// example from the signal references drawer, which links every tree to
// /decision-trees/<code>. The page now hands such a tree to the designer.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeViewerPage } from "./DecisionTreeViewerPage";

const state = vi.hoisted(() => ({
  beta: true,
  callerTenantId: null as string | null,
}));

function tree() {
  return {
    id: "tree-1",
    code: "medjool_bunch_health",
    tenant_id: null,
    name_en: "Medjool — bunch health",
    name_ar: null,
    description_en: null,
    description_ar: null,
    crop_paths: ["date_palm.medjool"],
    country_codes: ["EG"],
    soil_textures: [],
    scope: "block" as const,
    archived_at: null,
    current_version: null,
    versions: [
      {
        id: "ver-1",
        version: 1,
        tree_yaml: state.beta ? null : "code: medjool_bunch_health\nroot: root\nnodes: {}\n",
        definition: state.beta ? { code: "medjool_bunch_health", nodes: {} } : null,
        tree_compiled: {},
        created_at: "2026-10-03T10:00:00Z",
        published_at: null,
        notes: null,
      },
    ],
  };
}

const noopMutation = {
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};

vi.mock("@/queries/decisionTrees", () => ({
  useDecisionTree: () => ({ data: tree(), isLoading: false, isError: false }),
  useAppendDecisionTreeVersion: () => noopMutation,
  usePublishDecisionTreeVersion: () => noopMutation,
  useDiscardDecisionTreeVersion: () => noopMutation,
  useDryRunDecisionTree: () => noopMutation,
  useUpdateDecisionTree: () => noopMutation,
  useDecisionTreeCandidateBlocks: () => ({ data: [], isLoading: false, isError: false }),
  useDecisionTreeCandidateFarms: () => ({ data: [], isLoading: false, isError: false }),
  useRunDecisionTreeOnFarm: () => noopMutation,
}));
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
  useClaims: () => ({ tenant_id: state.callerTenantId }),
}));
vi.mock("@/api/signals", () => ({ listSignalDefinitions: () => Promise.resolve([]) }));
vi.mock("../components/TreeTargetingPicker", () => ({ TreeTargetingPicker: () => null }));
vi.mock("../components/TreeRolloutPanel", () => ({
  TreeRolloutPanel: () => <div data-testid="rollout" />,
}));
vi.mock("../components/ParameterOverridesPanel", () => ({
  ParameterOverridesPanel: () => <div data-testid="overrides" />,
}));

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/decision-trees/:code" element={<DecisionTreeViewerPage />} />
          <Route path="/platform/decision-trees/:code" element={<DecisionTreeViewerPage />} />
          <Route
            path="/platform/decision-trees-beta/:code"
            element={<div data-testid="beta-designer" />}
          />
          <Route path="/decision-trees-beta/:code" element={<div data-testid="beta-designer" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("a beta tree opened in the old viewer", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.beta = true;
  });

  it("goes to the beta designer for a platform admin", async () => {
    state.callerTenantId = null;
    renderAt("/decision-trees/medjool_bunch_health");

    expect(await screen.findByTestId("beta-designer")).toBeTruthy();
    expect(screen.queryByText("Tree has no nodes to display yet.")).toBeNull();
  });

  it("goes to the beta designer for a tenant", async () => {
    state.callerTenantId = "01a041ef-e184-723b-b1cb-9d6e656fe00d";
    renderAt("/decision-trees/medjool_bunch_health");

    expect(await screen.findByTestId("beta-designer")).toBeTruthy();
  });
});

describe("an old-engine tree", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.beta = false;
    state.callerTenantId = null;
  });

  it("stays in the old viewer", async () => {
    renderAt("/decision-trees/medjool_bunch_health");

    expect(await screen.findByText("Medjool — bunch health")).toBeTruthy();
    expect(screen.queryByTestId("beta-designer")).toBeNull();
  });
});
