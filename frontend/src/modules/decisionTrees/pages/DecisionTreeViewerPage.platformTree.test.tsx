// Who may edit which tree, and the page saying so when the answer is "not you".
//
// A platform tree is read-only *to a tenant*, and always was: the API refuses
// the write, and the refusal used to come back as "No decision tree with code
// 'mango_canopy_vigour_by_size_v1'" — about a tree the author had open on
// screen. Every one of the 33 shipped trees is a platform tree, so that was
// every shipped tree.
//
// It is no longer read-only to everyone. The reason it used to be was that the
// tree was owned by its YAML file and `sync_from_disk` rewrote it at the next
// restart. Public migration 0085 moved the definitions into the database and
// the startup sync is gone, so a platform admin edits these now — and only
// they do. Both halves are asserted here.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeViewerPage } from "./DecisionTreeViewerPage";

// Declares a parameter, so the overrides panel has something to render — it
// only appears on a tree that declares one.
const YAML = `code: qa_tree
name_en: QA tree
parameters:
  ndvi_floor:
    type: number
    default: 0.4
root: root
nodes:
  root:
    outcome:
      kind: status
      status: good
      text_en: Checked and fine.
`;

const VERSION = {
  id: "ver-1",
  version: 1,
  tree_yaml: YAML,
  tree_compiled: {},
  created_at: "2026-09-01T10:00:00Z",
  published_at: "2026-09-01T11:00:00Z",
  notes: null,
};

const state = vi.hoisted(() => ({
  // Who owns the tree on screen.
  tenantId: null as string | null,
  // Who is looking at it. Null means a platform admin, who has no tenant.
  callerTenantId: "01a041ef-e184-723b-b1cb-9d6e656fe00d" as string | null,
}));

function tree() {
  return {
    id: "tree-1",
    code: "qa_tree",
    tenant_id: state.tenantId,
    name_en: "QA tree",
    name_ar: null,
    description_en: null,
    description_ar: null,
    crop_paths: ["mango"],
    country_codes: [],
    soil_textures: [],
    scope: "block" as const,
    archived_at: null,
    current_version: 1,
    versions: [VERSION],
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
  useDryRunDecisionTree: () => noopMutation,
  useUpdateDecisionTree: () => noopMutation,
  useDecisionTreeCandidateBlocks: () => ({ data: [], isLoading: false, isError: false }),
  useDecisionTreeCandidateFarms: () => ({ data: [], isLoading: false, isError: false }),
  useRunDecisionTreeOnFarm: () => noopMutation,
}));
// The author holds decision_tree.manage. Ownership is the other half of the
// question, and it is the half this page was missing.
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
  // The authoring scope reads the caller's claims. A tenant_id means the
  // tenant catalogue, which is the scope every one of these cases assumes.
  useClaims: () => ({ tenant_id: state.callerTenantId }),
}));
vi.mock("@/api/signals", () => ({ listSignalDefinitions: () => Promise.resolve([]) }));
vi.mock("../components/TreeTargetingPicker", () => ({ TreeTargetingPicker: () => null }));
// The rollout panel fetches its own availability. These suites are about the
// editor, so stand it in; its own behaviour is covered separately.
vi.mock("../components/TreeRolloutPanel", () => ({
  TreeRolloutPanel: () => <div data-testid="rollout" />,
}));
vi.mock("../components/ParameterOverridesPanel", () => ({
  ParameterOverridesPanel: () => <div data-testid="overrides" />,
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/decision-trees/qa_tree"]}>
        <DecisionTreeViewerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("a platform tree", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.tenantId = null;
    state.callerTenantId = "01a041ef-e184-723b-b1cb-9d6e656fe00d";
  });

  it("offers no save or publish", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /save draft/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /publish/i })).toBeNull();
  });

  it("says why, rather than leaving the page inert", async () => {
    renderPage();

    expect(
      await screen.findByText(/This tree comes from the platform\. Your tenant cannot edit it here/),
    ).toBeTruthy();
  });

  it("keeps parameter overrides available", async () => {
    // The sanctioned way a tenant changes how a platform tree behaves. Hiding
    // it along with the rest would leave no way at all.
    renderPage();

    expect(await screen.findByTestId("overrides")).toBeTruthy();
  });
});

describe("a tenant's own tree", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.tenantId = "01a041ef-e184-723b-b1cb-9d6e656fe00d";
    state.callerTenantId = "01a041ef-e184-723b-b1cb-9d6e656fe00d";
  });

  it("is editable, and says nothing about being read-only", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
    expect(screen.queryByText(/This tree comes from the platform/)).toBeNull();
  });
});

describe("a platform tree, seen by a platform admin", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    // Both null: the tree is a platform row, and so is the caller's scope.
    // That pairing is what makes it editable, and it is the pairing the
    // 33 shipped trees had no caller for until public migration 0085.
    state.tenantId = null;
    state.callerTenantId = null;
  });

  it("is editable, and says nothing about being read-only", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
    expect(screen.queryByText(/This tree comes from the platform/)).toBeNull();
  });
});

describe("a platform tree in Arabic", () => {
  beforeEach(async () => {
    await setupTestI18n("ar");
    state.tenantId = null;
    state.callerTenantId = "01a041ef-e184-723b-b1cb-9d6e656fe00d";
  });

  it("says why in Arabic", async () => {
    renderPage();

    expect(await screen.findByText(/هذه الشجرة من المنصة/)).toBeTruthy();
  });
});
