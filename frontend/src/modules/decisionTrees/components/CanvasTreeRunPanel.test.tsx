import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeRunCandidateFarm, TreeRunResponse } from "@/api/decisionTrees";
import { setupTestI18n } from "@/i18n/testing";

import { CanvasTreeRunPanel } from "./CanvasTreeRunPanel";

const FARMS: TreeRunCandidateFarm[] = [
  {
    farm_id: "farm-1",
    name: "Bashier Elkhier",
    name_ar: null,
    blocks_total: 12,
    blocks_targeted: 4,
  },
];

function renderPanel(overrides: Partial<Parameters<typeof CanvasTreeRunPanel>[0]> = {}) {
  const onRun = vi.fn();
  render(
    <CanvasTreeRunPanel
      farmId="farm-1"
      onFarmIdChange={vi.fn()}
      candidateFarms={FARMS}
      candidatesLoading={false}
      canRun
      hasUnsavedDraft={false}
      isRunning={false}
      result={null}
      onRun={onRun}
      onClear={vi.fn()}
      {...overrides}
    />,
  );
  return { onRun };
}

function result(overrides: Partial<TreeRunResponse> = {}): TreeRunResponse {
  return {
    run_id: "run-1",
    farm_id: "farm-1",
    tree_code: "scout_for_stress_v1",
    tree_version: 3,
    scope: "block",
    blocks_evaluated: 4,
    blocks_targeted: 4,
    recommendations_opened: 2,
    deduped: 0,
    cleared: 2,
    errors: 0,
    traces_written: 4,
    blocks: [],
    ...overrides,
  };
}

describe("<CanvasTreeRunPanel>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("does not run on the first click — a write to a shared surface confirms first", async () => {
    const user = userEvent.setup();
    const { onRun } = renderPanel();

    await user.click(screen.getByRole("button", { name: /run for real/i }));
    expect(onRun).not.toHaveBeenCalled();
    // The confirm names the farm and how many blocks are actually in scope,
    // so "run" never means "run on more than I thought". Matched as one
    // sentence: the farm name also appears in the picker option.
    expect(
      screen.getByText(/opens real recommendations on 4 block\(s\) of Bashier Elkhier/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /yes, run it/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("cannot run a tree with no published version, and says why", () => {
    renderPanel({ canRun: false });
    expect(screen.getByRole("button", { name: /run for real/i })).toBeDisabled();
    expect(screen.getByText(/Publish a version first/i)).toBeInTheDocument();
  });

  it("warns that unsaved canvas edits are not what runs", () => {
    renderPanel({ hasUnsavedDraft: true });
    expect(screen.getByText(/unsaved edits are not included/i)).toBeInTheDocument();
  });

  it("reports a re-run's zero as 'already open', not as a failure", () => {
    // The regression this guards: the second run of a tree opens nothing
    // because the partial UNIQUE on open recommendations absorbs it. Showing
    // only "Nothing opened" would read as a broken run.
    renderPanel({ result: result({ recommendations_opened: 0, deduped: 4, cleared: 0 }) });

    expect(screen.getByText(/nothing opened/i)).toBeInTheDocument();
    expect(screen.getByText(/4 already open/i)).toBeInTheDocument();
  });

  it("reports what it opened and where to find it", () => {
    renderPanel({ result: result() });
    expect(screen.getByText(/2 recommendation\(s\) opened/i)).toBeInTheDocument();
    expect(screen.getByText("Open the Action Center to see them.")).toBeInTheDocument();
    // The version that ran, not the draft on screen.
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("shows the farm's targeted-vs-total block counts in the picker", () => {
    renderPanel();
    expect(screen.getByRole("option", { name: /4 of 12 block/i })).toBeInTheDocument();
  });

  it("tells the author when no farm can be run at all", () => {
    renderPanel({ candidateFarms: [] });
    expect(screen.getByText(/No farm has blocks matching/i)).toBeInTheDocument();
  });
});
