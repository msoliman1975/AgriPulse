// Discarding a draft version from the version history panel.
//
// Before this existed there was no way back from a save the author did not
// want. The editor hydrates from the NEWEST version, and `append_version`
// returns the existing row when the compiled hash is unchanged — so re-saving
// the old body did nothing, and the unwanted draft stayed in front of every
// later author.
//
// The button is offered on an unpublished, non-current version only. A
// published version is the record of what the engine ran and the API refuses
// to delete one, so offering the button there would be a lie.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

interface VersionRow {
  id: string;
  version: number;
  tree_yaml: string;
  tree_compiled: Record<string, unknown>;
  created_at: string;
  published_at: string | null;
  notes: string | null;
}

function version(n: number, published: boolean): VersionRow {
  return {
    id: `ver-${n}`,
    version: n,
    tree_yaml: YAML,
    tree_compiled: {},
    created_at: "2026-09-01T10:00:00Z",
    published_at: published ? "2026-09-01T11:00:00Z" : null,
    notes: null,
  };
}

// `vi.hoisted` runs before the module body, so the rows are built in
// `beforeEach` where `YAML` exists. Newest first, the order the API returns.
const state = vi.hoisted(() => ({ versions: [] as VersionRow[] }));

const discardMutation = vi.hoisted(() => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn().mockResolvedValue(undefined),
  isPending: false,
  isError: false,
  error: null,
}));

const noopMutation = vi.hoisted(() => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
}));

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
      crop_paths: ["mango"],
      country_codes: [],
      soil_textures: [],
      scope: "block" as const,
      archived_at: null,
      current_version: 1,
      versions: state.versions,
    },
    isLoading: false,
    isError: false,
  }),
  useAppendDecisionTreeVersion: () => noopMutation,
  usePublishDecisionTreeVersion: () => noopMutation,
  useDiscardDecisionTreeVersion: () => discardMutation,
  useDryRunDecisionTree: () => noopMutation,
  useUpdateDecisionTree: () => noopMutation,
  useDecisionTreeCandidateBlocks: () => ({ data: [], isLoading: false, isError: false }),
  useDecisionTreeCandidateFarms: () => ({ data: [], isLoading: false, isError: false }),
  useRunDecisionTreeOnFarm: () => noopMutation,
}));
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
  useClaims: () => ({ tenant_id: null }),
}));
vi.mock("@/api/signals", () => ({ listSignalDefinitions: () => Promise.resolve([]) }));
vi.mock("../components/TreeTargetingPicker", () => ({ TreeTargetingPicker: () => null }));
vi.mock("../components/TreeRolloutPanel", () => ({
  TreeRolloutPanel: () => <div data-testid="rollout" />,
}));
vi.mock("../components/ParameterOverridesPanel", () => ({
  ParameterOverridesPanel: () => <div data-testid="overrides" />,
}));

async function openVersionHistory(user: ReturnType<typeof userEvent.setup>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/platform/decision-trees/qa_tree"]}>
        <DecisionTreeViewerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("QA tree")).toBeTruthy());
  // The panel is collapsed by default; both Expand buttons open a section and
  // the last one is the version history.
  const expanders = screen.getAllByRole("button", { name: /expand details/i });
  await user.click(expanders[expanders.length - 1]);
}

describe("discarding a draft version", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    state.versions = [version(2, false), version(1, true)];
    discardMutation.mutateAsync.mockClear();
  });

  it("sends the discard after the author confirms", async () => {
    const user = userEvent.setup();
    await openVersionHistory(user);

    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    // Nothing is sent on the button alone — the dialog names the version.
    expect(discardMutation.mutateAsync).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Discard draft v2?")).toBeTruthy();

    await user.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    // The version is what this test is about. `code` comes from `useParams`
    // and is "" here, because the page is mounted without a path pattern.
    await waitFor(() =>
      expect(discardMutation.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ version: 2 }),
      ),
    );
  });

  it("offers nothing on a published version", async () => {
    state.versions = [version(2, true), version(1, true)];
    const user = userEvent.setup();
    await openVersionHistory(user);

    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
  });

  it("offers nothing when the draft is the tree's only version", async () => {
    // Discarding it would leave the editor nothing to open, and the API
    // refuses it, so the button is not there to press.
    state.versions = [version(1, false)];
    const user = userEvent.setup();
    await openVersionHistory(user);

    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
  });
});
