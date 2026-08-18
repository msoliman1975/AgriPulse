// Which version the workspace loads.
//
// Two bugs, one root: the editor resolved its source version as "the
// published one, falling back to the latest".
//
//  * On a published tree that meant every draft you saved vanished from
//    the editor the moment it saved — the canvas snapped back to the
//    published YAML, and the next save was computed from the published
//    version again, dropping the draft in between.
//  * "Load into editor" set the hydrated-from id to the chosen version;
//    the hydrate effect then saw it differ from the published version's
//    id and immediately pulled the published YAML back over the top, so
//    the button did nothing at all.
//
// Both are about the same two lines, and both are invisible in a
// screenshot — the canvas looks fine, it is just showing the wrong
// version — so they are pinned here.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeViewerPage } from "./DecisionTreeViewerPage";

function versionYaml(marker: string): string {
  return `code: qa_tree
name_en: ${marker}
root: root
nodes:
  root:
    outcome:
      action_type: no_action
      kind: recommendation
      text_en: ${marker}
`;
}

const V1 = {
  id: "ver-1",
  version: 1,
  tree_yaml: versionYaml("published-v1"),
  tree_compiled: {},
  created_at: "2026-08-01T10:00:00Z",
  published_at: "2026-08-01T11:00:00Z",
  notes: null,
};
const V2 = {
  id: "ver-2",
  version: 2,
  tree_yaml: versionYaml("draft-v2"),
  tree_compiled: {},
  created_at: "2026-08-02T10:00:00Z",
  published_at: null,
  notes: null,
};
// A third version so the "load a historical version" case can pick one
// that is neither the published version nor the latest. With only two,
// loading v1 on the old code happened to be a no-op — it was already the
// version being shown — and the test passed against the bug.
const V3 = {
  id: "ver-3",
  version: 3,
  tree_yaml: versionYaml("draft-v3"),
  tree_compiled: {},
  created_at: "2026-08-03T10:00:00Z",
  published_at: null,
  notes: null,
};

// A published tree whose newest version is an unpublished draft — the
// exact state an author is in one save after publishing.
const TREE = {
  id: "tree-1",
  code: "qa_tree",
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
  // Newest first, the order the API returns.
  versions: [V3, V2, V1],
};

const noopMutation = {
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};

vi.mock("@/queries/decisionTrees", () => ({
  useDecisionTree: () => ({ data: TREE, isLoading: false, isError: false }),
  useAppendDecisionTreeVersion: () => noopMutation,
  usePublishDecisionTreeVersion: () => noopMutation,
  useDryRunDecisionTree: () => noopMutation,
  useUpdateDecisionTree: () => noopMutation,
  useDecisionTreeCandidateBlocks: () => ({ data: [], isLoading: false, isError: false }),
  useDecisionTreeCandidateFarms: () => ({ data: [], isLoading: false, isError: false }),
  useRunDecisionTreeOnFarm: () => noopMutation,
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/api/signals", () => ({ listSignalDefinitions: () => Promise.resolve([]) }));
vi.mock("../components/TreeTargetingPicker", () => ({
  TreeTargetingPicker: () => null,
}));
vi.mock("../components/ParameterOverridesPanel", () => ({
  ParameterOverridesPanel: () => null,
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/decision-trees/qa_tree"]}>
        <DecisionTreeViewerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function yamlSource(user: ReturnType<typeof userEvent.setup>): Promise<HTMLTextAreaElement> {
  await user.click(screen.getByRole("tab", { name: "YAML" }));
  return screen.getByLabelText<HTMLTextAreaElement>("Tree YAML source");
}

describe("DecisionTreeViewerPage version hydration", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("edits the latest version, not the published one", async () => {
    const user = userEvent.setup();
    renderPage();

    const source = await yamlSource(user);

    await waitFor(() => expect(source.value).toContain("draft-v3"));
    expect(source.value).not.toContain("published-v1");
  });

  it("loads a historical version when asked, and keeps it loaded", async () => {
    const user = userEvent.setup();
    renderPage();

    // Version history is collapsed by default.
    await user.click(screen.getByRole("button", { name: /Expand details/i }));
    const loadButtons = screen.getAllByRole("button", { name: "Load into editor" });
    // Rendered newest-first: [v3, v2, v1]. v2 is neither the published
    // version nor the latest, so loading it is a real switch under either
    // reading of "source version".
    await user.click(loadButtons[1]);

    const source = await yamlSource(user);

    await waitFor(() => expect(source.value).toContain("draft-v2"));
    // The regression: the hydrate effect used to overwrite this on the very
    // next render, silently putting the source version back.
    expect(source.value).not.toContain("draft-v3");
    expect(source.value).not.toContain("published-v1");
  });
});
