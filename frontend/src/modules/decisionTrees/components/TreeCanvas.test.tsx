import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { layoutTree, type CompiledTree } from "../layout/treeLayout";
import { TreeCanvas } from "./TreeCanvas";

// jsdom has no PointerEvent. React only looks at the event *type*, so
// a MouseEvent named "pointerdown" drives the same handlers, and
// MouseEvent carries the clientX/clientY the drag maths reads.
function firePointer(
  target: EventTarget,
  type: "pointerdown" | "pointermove" | "pointerup",
  init: { clientX?: number; clientY?: number; button?: number } = {},
): void {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: init.button ?? 0,
    clientX: init.clientX ?? 0,
    clientY: init.clientY ?? 0,
  });
  act(() => {
    target.dispatchEvent(event);
  });
}

const COMPILED: CompiledTree = {
  root: "root",
  nodes: {
    root: { label_en: "ndvi below floor", on_match: "hit", on_miss: "skip" },
    hit: { outcome: { action_type: "irrigate", text_en: "water it" } },
    skip: { label_en: "second check", on_match: "leaf2" },
    leaf2: { outcome: { action_type: "no_action" } },
  },
};

const LAYOUT = layoutTree(COMPILED);

function nodeGroup(nodeId: string): SVGGElement {
  // Every box prints its own id in a monospace label; the enclosing
  // <g> is the drag/click target.
  const label = screen.getByText(nodeId);
  const group = label.closest("g");
  if (!group) throw new Error(`no group for node ${nodeId}`);
  return group;
}

function worldTransform(): string {
  const world = document.querySelector("[data-tree-world]");
  return world?.getAttribute("transform") ?? "";
}

interface Overrides {
  onNodeMove?: (nodeId: string, x: number, y: number) => void;
  onSelectNode?: (nodeId: string | null) => void;
  onResetLayout?: () => void;
  canResetLayout?: boolean;
  onHeightChange?: (height: number) => void;
  onAddChild?: (parentId: string, branch: "match" | "miss") => void;
}

function renderCanvas(overrides: Overrides = {}) {
  const props = {
    onNodeMove: vi.fn(),
    onSelectNode: vi.fn(),
    onResetLayout: vi.fn(),
    onHeightChange: vi.fn(),
    onAddChild: vi.fn(),
    canResetLayout: false,
    ...overrides,
  };
  render(
    <TreeCanvas
      layout={LAYOUT}
      height={560}
      onHeightChange={props.onHeightChange}
      onNodeMove={props.onNodeMove}
      onSelectNode={props.onSelectNode}
      onResetLayout={props.onResetLayout}
      canResetLayout={props.canResetLayout}
      onAddChild={props.onAddChild}
      exportFileName="tree.png"
    />,
  );
  return props;
}

describe("TreeCanvas controls", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("starts at 100% and zooms with the toolbar buttons", async () => {
    const user = userEvent.setup();
    renderCanvas();
    expect(screen.getByText("100%")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("120%")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByText("100%")).toBeTruthy();
  });

  it("does not zoom past the limits", async () => {
    const user = userEvent.setup();
    renderCanvas();
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    for (let i = 0; i < 20; i += 1) {
      await user.click(zoomIn);
    }
    // MAX_SCALE is 2.5.
    expect(screen.getByText("250%")).toBeTruthy();
  });

  it("reports the node count", () => {
    renderCanvas();
    expect(screen.getByText(/4 nodes/)).toBeTruthy();
  });

  it("disables Reset layout until something has been moved", () => {
    renderCanvas({ canResetLayout: false });
    const button = screen.getByRole("button", { name: "Reset layout" });
    expect(button.getAttribute("disabled")).not.toBeNull();
  });

  it("calls onResetLayout when boxes have been moved", async () => {
    const user = userEvent.setup();
    const props = renderCanvas({ canResetLayout: true });
    await user.click(screen.getByRole("button", { name: "Reset layout" }));
    expect(props.onResetLayout).toHaveBeenCalledTimes(1);
  });
});

describe("TreeCanvas box dragging", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("moves the box by the pointer delta", () => {
    const props = renderCanvas();
    const node = LAYOUT.nodes.find((n) => n.id === "hit")!;

    firePointer(nodeGroup("hit"), "pointerdown", { clientX: 400, clientY: 300 });
    firePointer(window, "pointermove", { clientX: 460, clientY: 345 });

    expect(props.onNodeMove).toHaveBeenCalledWith("hit", node.x + 60, node.y + 45);
  });

  it("never lets a box go negative", () => {
    const props = renderCanvas();
    firePointer(nodeGroup("hit"), "pointerdown", { clientX: 400, clientY: 300 });
    firePointer(window, "pointermove", { clientX: -9000, clientY: -9000 });
    expect(props.onNodeMove).toHaveBeenCalledWith("hit", 0, 0);
  });

  it("selects the box on a click with no movement", () => {
    const props = renderCanvas();
    const group = nodeGroup("hit");
    firePointer(group, "pointerdown", { clientX: 400, clientY: 300 });
    firePointer(window, "pointerup", { clientX: 400, clientY: 300 });
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(props.onSelectNode).toHaveBeenCalledWith("hit");
  });

  it("does not select the box on the click that ends a drag", () => {
    const props = renderCanvas();
    const group = nodeGroup("hit");
    firePointer(group, "pointerdown", { clientX: 400, clientY: 300 });
    firePointer(window, "pointermove", { clientX: 500, clientY: 380 });
    firePointer(window, "pointerup", { clientX: 500, clientY: 380 });
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(props.onSelectNode).not.toHaveBeenCalled();
  });

  it("leaves boxes alone when box dragging is off", () => {
    render(
      <TreeCanvas layout={LAYOUT} height={560} onHeightChange={vi.fn()} onSelectNode={vi.fn()} />,
    );
    const group = nodeGroup("hit");
    firePointer(group, "pointerdown", { clientX: 400, clientY: 300 });
    firePointer(window, "pointermove", { clientX: 500, clientY: 380 });
    // With no onNodeMove the pointerdown falls through to the pan
    // handler, which is the background behaviour, not a box move.
    expect(worldTransform()).toContain("translate(100 80)");
  });
});

describe("TreeCanvas panning", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("pans on a background drag", () => {
    renderCanvas();
    expect(worldTransform()).toBe("translate(0 0) scale(1)");
    const svg = document.querySelector("svg")!;
    firePointer(svg, "pointerdown", { clientX: 200, clientY: 200 });
    firePointer(window, "pointermove", { clientX: 230, clientY: 180 });
    expect(worldTransform()).toBe("translate(30 -20) scale(1)");
  });

  it("deselects on a background click that did not pan", () => {
    const props = renderCanvas();
    const svg = document.querySelector("svg")!;
    firePointer(svg, "pointerdown", { clientX: 200, clientY: 200 });
    firePointer(window, "pointerup", { clientX: 200, clientY: 200 });
    act(() => {
      svg.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(props.onSelectNode).toHaveBeenCalledWith(null);
  });

  it("does not deselect on the click that ends a pan", () => {
    const props = renderCanvas();
    const svg = document.querySelector("svg")!;
    firePointer(svg, "pointerdown", { clientX: 200, clientY: 200 });
    firePointer(window, "pointermove", { clientX: 260, clientY: 200 });
    firePointer(window, "pointerup", { clientX: 260, clientY: 200 });
    act(() => {
      svg.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(props.onSelectNode).not.toHaveBeenCalled();
  });
});

describe("TreeCanvas height grip", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("grows the canvas on a grip drag", () => {
    const props = renderCanvas();
    const grip = screen.getByRole("button", { name: "Drag to change the canvas height" });
    firePointer(grip, "pointerdown", { clientX: 0, clientY: 700 });
    firePointer(window, "pointermove", { clientX: 0, clientY: 820 });
    expect(props.onHeightChange).toHaveBeenCalledWith(680);
  });
});

describe("TreeCanvas ports still work", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("adds a child from an empty port", async () => {
    const user = userEvent.setup();
    const props = renderCanvas();
    // "skip" has on_match wired and on_miss empty. The port carries an
    // SVG <title>, which is not a direct child of <svg>, so getByTitle
    // does not see it — match on its text instead.
    const port = screen.getByText("Add miss child").closest("g");
    expect(port).not.toBeNull();
    await user.click(port!);
    expect(props.onAddChild).toHaveBeenCalledWith("skip", "miss");
  });
});
