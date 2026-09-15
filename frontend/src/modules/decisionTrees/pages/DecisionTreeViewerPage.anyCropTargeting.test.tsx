// Editing the targeting of a tree that targets every crop.
//
// An empty crop set means "matches any", the same as an empty country or soil
// set. 20 of the 41 platform trees store it. The editor used to also treat it
// as "no crop picked yet" and disable Save whenever the targeting was dirty,
// with nothing on the button saying why. So on those trees a country, soil or
// execution-scope change could not be saved at all: the click did nothing, no
// draft was appended, and the header's "Publish vN" button — which only shows
// when an unpublished draft exists — never appeared.
//
// The backend half is `DecisionTreeUpdateRequest.crop_paths`, covered in
// backend/tests/unit/recommendations/test_update_request_targeting.py.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeViewerPage } from "./DecisionTreeViewerPage";

const YAML = `code: qa_tree
name_en: QA tree
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

const state = vi.hoisted(() => ({ cropPaths: [] as string[] }));

vi.mock("@/queries/decisionTrees", () => ({
  useDecisionTree: () => ({
    data: {
      id: "tree-1",
      code: "qa_tree",
      tenant_id: null,
      name_en: "QA tree",
      name_ar: null,
      description_en: null,
      description_ar: null,
      crop_paths: state.cropPaths,
      country_codes: [],
      soil_textures: [],
      scope: "block" as const,
      archived_at: null,
      current_version: 1,
      versions: [VERSION],
    },
    isLoading: false,
    isError: false,
  }),
  useAppendDecisionTreeVersion: () => noopMutation,
  usePublishDecisionTreeVersion: () => noopMutation,
  useDryRunDecisionTree: () => noopMutation,
  useUpdateDecisionTree: () => noopMutation,
  useDecisionTreeCandidateBlocks: () => ({ data: [], isLoading: false, isError: false }),
  useDecisionTreeCandidateFarms: () => ({ data: [], isLoading: false, isError: false }),
  useRunDecisionTreeOnFarm: () => noopMutation,
}));

const noopMutation = vi.hoisted(() => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
}));

// A platform admin looking at a platform tree: the pairing that may edit it.
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
  useClaims: () => ({ tenant_id: null }),
}));
vi.mock("@/api/signals", () => ({ listSignalDefinitions: () => Promise.resolve([]) }));
vi.mock("../components/TreeRolloutPanel", () => ({
  TreeRolloutPanel: () => <div data-testid="rollout" />,
}));
vi.mock("../components/ParameterOverridesPanel", () => ({
  ParameterOverridesPanel: () => <div data-testid="overrides" />,
}));
// Stand in for the picker so the test can make exactly one targeting change —
// adding a country — without driving the real crop/country/soil widgets.
vi.mock("../components/TreeTargetingPicker", () => ({
  TreeTargetingPicker: ({
    onCountryCodesChange,
  }: {
    onCountryCodesChange: (next: string[]) => void;
  }) => (
    <button type="button" onClick={() => onCountryCodesChange(["EG"])}>
      add Egypt
    </button>
  ),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/platform/decision-trees/qa_tree"]}>
        <DecisionTreeViewerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("targeting a tree that matches any crop", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.cropPaths = [];
  });

  it("offers a Save the author can actually press", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "add Egypt" }));

    const save = await screen.findByRole("button", { name: /save as new draft/i });
    expect((save as HTMLButtonElement).disabled).toBe(false);
  });

  it("still offers it on a tree that names a crop", async () => {
    state.cropPaths = ["mango"];
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "add Egypt" }));

    const save = await screen.findByRole("button", { name: /save as new draft/i });
    expect((save as HTMLButtonElement).disabled).toBe(false);
  });
});
