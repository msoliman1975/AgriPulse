// A whole-block verdict says what the tree concluded, and offers the walk.
//
// A block tree writes one verdict with no cell, so it produces no areas, and
// the area card is where the sentence and the reasoning toggle lived. The
// panel showed the colour bar, the words "1 Good", and "This block has no
// cell verdicts for this tree" — no message, no way to ask why. Both were in
// the payload the page already had.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StatusDefinition, Verdict } from "@/api/farmHealth";
import { setupTestI18n } from "@/i18n/testing";

import { BlockVerdictDetail } from "./AreaPanel";

const reasoning = vi.hoisted(() => ({ fn: vi.fn() }));

vi.mock("@/api/farmHealth", async () => {
  const actual = await vi.importActual<typeof import("@/api/farmHealth")>("@/api/farmHealth");
  return { ...actual, getVerdictReasoning: reasoning.fn };
});

const STATUSES: StatusDefinition[] = [
  { code: "na", rank: 0, color: "#9AA0A6", label_en: "Not applicable", label_ar: "لا ينطبق" },
  { code: "very_good", rank: 1, color: "#1B873F", label_en: "Very good", label_ar: "ممتاز" },
  { code: "good", rank: 2, color: "#6FBF4B", label_en: "Good", label_ar: "جيد" },
  { code: "issue", rank: 3, color: "#E8A33D", label_en: "Issue", label_ar: "مشكلة" },
  { code: "alert", rank: 4, color: "#D64545", label_en: "Alert", label_ar: "إنذار" },
];

const VERDICT: Verdict = {
  id: "verdict-1",
  farm_id: "farm-1",
  block_id: "block-10",
  cell_id: null,
  cell_row: null,
  cell_col: null,
  scope: "block",
  tree_id: "tree-1",
  tree_code: "mango_canopy_health_v1",
  tree_version: 4,
  leaf_node_id: "leaf_no_action",
  kind: "status",
  status_code: "good",
  severity: null,
  text_en: "Canopy greenness is within the seasonal baseline.",
  text_ar: "خضرة المجموع الخضري ضمن الأساس الموسمي.",
  valid_from: "2026-09-08T15:17:00Z",
  valid_to: null,
  last_evaluated_at: "2026-09-08T15:17:00Z",
  alert_id: null,
  recommendation_id: null,
};

function renderCard(open = false, onToggle = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BlockVerdictDetail
        verdict={VERDICT}
        statuses={STATUSES}
        farmId="farm-1"
        blockId="block-10"
        open={open}
        onToggle={onToggle}
      />
    </QueryClientProvider>,
  );
  return onToggle;
}

describe("a whole-block verdict", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    reasoning.fn.mockReset();
    reasoning.fn.mockResolvedValue({
      verdict_id: "verdict-1",
      block_id: "block-10",
      cell_id: null,
      cell_row: null,
      cell_col: null,
      scope: "block",
      tree_id: "tree-1",
      tree_code: "mango_canopy_health_v1",
      tree_version: 4,
      leaf_node_id: "leaf_no_action",
      kind: "status",
      status_code: "good",
      severity: null,
      valid_from: "2026-09-08T15:17:00Z",
      last_evaluated_at: "2026-09-08T15:17:00Z",
      reasoning_available: true,
      trace_id: "trace-1",
      node_path: [],
      resolved_values: {},
    });
  });

  it("shows the sentence the tree wrote", async () => {
    renderCard();

    expect(
      await screen.findByText("Canopy greenness is within the seasonal baseline."),
    ).toBeTruthy();
  });

  it("names the status and the version that decided it", async () => {
    renderCard();

    expect(await screen.findByText("Good")).toBeTruthy();
    expect(screen.getByText(/mango_canopy_health_v1 · v4/)).toBeTruthy();
  });

  it("offers the walk behind it", async () => {
    const onToggle = renderCard(false);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /how this was decided/i }));

    expect(onToggle).toHaveBeenCalled();
  });

  it("asks for the reasoning only once it is opened", () => {
    renderCard(false);

    expect(reasoning.fn).not.toHaveBeenCalled();
  });

  it("loads the walk when open", async () => {
    renderCard(true);

    await vi.waitFor(() =>
      expect(reasoning.fn).toHaveBeenCalledWith("block-10", "verdict-1", "farm-1"),
    );
  });
});

describe("a whole-block verdict in Arabic", () => {
  beforeEach(async () => {
    await setupTestI18n("ar");
  });

  it("shows the tree's own Arabic sentence, not a translation of the status", async () => {
    renderCard();

    expect(await screen.findByText("خضرة المجموع الخضري ضمن الأساس الموسمي.")).toBeTruthy();
    expect(screen.getByText("جيد")).toBeTruthy();
  });
});
