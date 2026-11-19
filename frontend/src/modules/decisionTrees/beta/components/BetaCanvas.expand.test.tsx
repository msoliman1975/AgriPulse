// Expanding the canvas for a big tree, and the level bands that read its depth.

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { layoutBetaTree } from "../lib/betaLayout";
import { parseBetaDoc } from "../lib/betaTree";
import { levelBands } from "../lib/levelBands";
import { BetaCanvas } from "./BetaCanvas";

// cond_1 (level 1) → reg_1 (level 2) → stop_1 (level 3). The stop is also
// cond_1's miss target, but an edge always points down, so it sits below reg_1.
const YAML = `root: cond_1
nodes:
  cond_1:
    label_en: Is leaf water low?
    condition:
      tree: { op: lt, left: { source: indices, index_code: ndmi, key: baseline_deviation }, right: -0.1 }
    on_match: reg_1
    on_miss: stop_1
  reg_1:
    label_en: Record it
    register: { code: dry, severity: warning }
    next: stop_1
  stop_1:
    label_en: End
    stop: true
`;

const layout = layoutBetaTree(parseBetaDoc(YAML));

function renderCanvas() {
  render(
    <BetaCanvas
      layout={layout}
      selectedNodeId={null}
      onSelectNode={vi.fn()}
      height={560}
      onHeightChange={vi.fn()}
    />,
  );
}

describe("levelBands", () => {
  it("gives one band per depth, in order, spanning that depth's nodes", () => {
    const bands = levelBands(layout);
    expect(bands.map((b) => [b.depth, b.count])).toEqual([
      [0, 1],
      [1, 1],
      [2, 1],
    ]);
    const cond = layout.byId.get("cond_1")!;
    expect(bands[0].top).toBe(cond.y);
    expect(bands[0].bottom).toBe(cond.y + cond.height);
    for (let i = 1; i < bands.length; i++) {
      expect(bands[i].top).toBeGreaterThanOrEqual(bands[i - 1].bottom);
    }
  });
});

describe("<BetaCanvas> expand and levels", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("counts the levels in the toolbar and draws no bands until asked", () => {
    renderCanvas();
    expect(screen.getByText(/3 levels/)).toBeInTheDocument();
    expect(screen.queryByTestId("level-bands")).toBeNull();
  });

  it("draws a labelled band per level when levels are shown", () => {
    renderCanvas();
    fireEvent.click(screen.getByRole("button", { name: "Show levels" }));
    const bands = screen.getByTestId("level-bands");
    expect(within(bands).getByText("Level 1")).toBeInTheDocument();
    expect(within(bands).getByText("Level 2")).toBeInTheDocument();
    expect(within(bands).getByText("Level 3")).toBeInTheDocument();
    expect(within(bands).getAllByText("1 node")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Hide levels" }));
    expect(screen.queryByTestId("level-bands")).toBeNull();
  });

  it("expands to a full-window view with the levels on, and Esc closes it", () => {
    renderCanvas();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    const dialog = screen.getByRole("dialog", { name: /full view/ });
    expect(dialog.className).toContain("fixed");
    expect(screen.getByTestId("level-bands")).toBeInTheDocument();
    // No resize grip in the full view: the window is the size.
    expect(screen.queryByRole("button", { name: "Drag to resize the canvas" })).toBeNull();

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Drag to resize the canvas" })).toBeInTheDocument();
  });

  it("closes from its own button too", () => {
    renderCanvas();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    fireEvent.click(screen.getByRole("button", { name: "Exit full view" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers Fit to width beside Fit to screen", () => {
    renderCanvas();
    expect(screen.getByRole("button", { name: "Fit to width" })).toBeInTheDocument();
  });

  it("pans on a plain wheel in the full view, and leaves the page to scroll inline", () => {
    renderCanvas();
    const surface = screen.getByRole("application");
    const graph = (): string | null =>
      surface.querySelector("svg > g")?.getAttribute("transform") ?? null;

    const inline = new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true });
    const before = graph();
    act(() => {
      surface.dispatchEvent(inline);
    });
    expect(inline.defaultPrevented).toBe(false);
    expect(graph()).toBe(before);

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    const expandedSurface = screen.getByRole("application");
    const start = expandedSurface.querySelector("svg > g")?.getAttribute("transform");
    const full = new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true });
    act(() => {
      expandedSurface.dispatchEvent(full);
    });
    expect(full.defaultPrevented).toBe(true);
    expect(expandedSurface.querySelector("svg > g")?.getAttribute("transform")).not.toBe(start);
  });
});
