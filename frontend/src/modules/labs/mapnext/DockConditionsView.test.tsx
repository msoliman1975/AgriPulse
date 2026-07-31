import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExplainBlockResponse } from "@/api/recommendations";
import { setupTestI18n } from "@/i18n/testing";

import { DockConditionsView } from "./DockConditionsView";

const h = vi.hoisted(() => ({ explainMock: vi.fn() }));

vi.mock("@/api/recommendations", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/recommendations")>("@/api/recommendations");
  return { ...actual, explainBlock: h.explainMock };
});

function tree(over: Partial<ExplainBlockResponse["trees"][number]>) {
  return {
    tree_id: "t1",
    code: "irrigation_v3",
    name_en: "Irrigation",
    name_ar: null,
    version: 3,
    scope: "block",
    status: "clear" as const,
    steps: [],
    kind: null,
    action_type: null,
    severity: null,
    confidence: null,
    text_en: null,
    text_ar: null,
    error: null,
    ...over,
  };
}

const FAILING_TREE = tree({
  tree_id: "t1",
  status: "fired",
  text_en: "Irrigate 30 mm within 24 hours.",
  steps: [
    {
      node_id: "soil",
      matched: false,
      label_en: "Soil moisture within target range",
      label_ar: null,
      values: { "signals.soil_moisture.value": "22" },
      condition: {
        op: "between",
        left: { source: "signals", code: "soil_moisture", key: "value" },
        low: 35,
        high: 50,
      },
    },
    {
      node_id: "leaf_irrigate",
      matched: null,
      label_en: "Emergency irrigation",
      label_ar: null,
      values: {},
      condition: null,
    },
  ],
});

function renderView(node: ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("DockConditionsView", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.explainMock.mockReset();
  });

  it("shows each check with the measured value and the threshold it missed", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: "citrus.valencia",
      trees: [FAILING_TREE],
    } satisfies ExplainBlockResponse);

    renderView(<DockConditionsView blockId="b1" farmId="f1" />);

    await waitFor(() =>
      expect(screen.getByText("Soil moisture within target range")).toBeTruthy(),
    );
    // "22 · 35–50" — the number and the band it had to sit inside.
    expect(screen.getByText(/22/)).toBeTruthy();
    expect(screen.getByText(/35–50/)).toBeTruthy();
    expect(screen.getByText(/Irrigate 30 mm within 24 hours\./)).toBeTruthy();
  });

  it("lists trees that came out clear — they leave no recommendation behind", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: "citrus.valencia",
      trees: [
        tree({ tree_id: "t2", name_en: "Pest risk", status: "clear", steps: [] }),
      ],
    } satisfies ExplainBlockResponse);

    renderView(<DockConditionsView blockId="b1" farmId="f1" />);

    // Appears twice — once in the tree list, once as the detail-pane heading.
    await waitFor(() => expect(screen.getAllByText("Pest risk").length).toBeGreaterThan(0));
    expect(screen.getAllByText(/clear/i).length).toBeGreaterThan(0);
  });

  it("reports the failing-check count to the tab badge", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: null,
      trees: [FAILING_TREE],
    } satisfies ExplainBlockResponse);

    const onCount = vi.fn();
    renderView(<DockConditionsView blockId="b1" farmId="f1" onFailingCountChange={onCount} />);

    await waitFor(() => expect(onCount).toHaveBeenCalledWith(1));
  });

  it("switches the detail pane when another tree is picked", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: null,
      trees: [
        FAILING_TREE,
        tree({ tree_id: "t2", name_en: "Growth stage", code: "growth_v1", status: "clear" }),
      ],
    } satisfies ExplainBlockResponse);

    renderView(<DockConditionsView blockId="b1" farmId="f1" />);

    await waitFor(() => expect(screen.getByText("Growth stage")).toBeTruthy());
    await userEvent.click(screen.getByRole("button", { name: /Growth stage/ }));
    await waitFor(() =>
      expect(screen.getByText(/reached its outcome without evaluating/i)).toBeTruthy(),
    );
  });

  it("explains an empty block instead of showing a blank pane", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: null,
      // Every tree excluded by targeting — the "no crop assigned" case.
      trees: [tree({ status: "skipped" }), tree({ tree_id: "t2", status: "skipped" })],
    } satisfies ExplainBlockResponse);

    renderView(<DockConditionsView blockId="b1" farmId="f1" />);

    await waitFor(() =>
      expect(screen.getByText(/No decision tree targets this block/i)).toBeTruthy(),
    );
  });

  it("does not give a cell-scoped tree a block-level verdict", async () => {
    h.explainMock.mockResolvedValue({
      block_id: "b1",
      evaluated_at: "2026-06-30T00:00:00Z",
      crop_path: null,
      trees: [tree({ tree_id: "t3", name_en: "Zone anomaly", scope: "cell", status: "per_cell" })],
    } satisfies ExplainBlockResponse);

    renderView(<DockConditionsView blockId="b1" farmId="f1" />);

    await waitFor(() =>
      expect(screen.getByText(/runs per grid cell, not per block/i)).toBeTruthy(),
    );
  });
});
