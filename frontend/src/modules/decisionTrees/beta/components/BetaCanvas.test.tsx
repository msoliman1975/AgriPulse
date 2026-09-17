import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { layoutBetaTree } from "../lib/betaLayout";
import { parseBetaDoc } from "../lib/betaTree";
import { BetaCanvas } from "./BetaCanvas";

// jsdom has no PointerEvent. React reads the event *type*, so a MouseEvent
// named "pointerdown" drives the same handlers and carries the clientX and
// clientY the drag maths reads. Without this a drag test passes while
// testing nothing.
function firePointer(
  target: EventTarget,
  type: "pointerdown" | "pointermove" | "pointerup",
  init: { clientX?: number; clientY?: number } = {},
): void {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: 0,
    clientX: init.clientX ?? 0,
    clientY: init.clientY ?? 0,
  });
  act(() => {
    target.dispatchEvent(event);
  });
}

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

function renderCanvas(overrides: Partial<Parameters<typeof BetaCanvas>[0]> = {}) {
  const onMoveNode = vi.fn();
  const onSelectNode = vi.fn();
  const onResetLayout = vi.fn();
  const layout = layoutBetaTree(parseBetaDoc(YAML));
  render(
    <BetaCanvas
      layout={layout}
      selectedNodeId={null}
      onSelectNode={onSelectNode}
      onMoveNode={onMoveNode}
      onResetLayout={onResetLayout}
      height={560}
      onHeightChange={vi.fn()}
      {...overrides}
    />,
  );
  return { onMoveNode, onSelectNode, onResetLayout, layout };
}

function nodeGroup(nodeId: string): SVGGElement {
  const group = document.querySelector(`[data-node-id="${nodeId}"]`);
  if (!group) throw new Error(`no group for node ${nodeId}`);
  return group as SVGGElement;
}

beforeEach(async () => {
  await setupTestI18n("en");
});

describe("<BetaCanvas> node dragging", () => {
  it("reports the drop position, measured from where the node was", () => {
    const { onMoveNode, layout } = renderCanvas();
    const start = layout.byId.get("reg_1")!;

    firePointer(nodeGroup("reg_1"), "pointerdown", { clientX: 100, clientY: 100 });
    firePointer(window, "pointermove", { clientX: 160, clientY: 140 });
    firePointer(window, "pointerup", {});

    expect(onMoveNode).toHaveBeenCalledWith("reg_1", start.x + 60, start.y + 40);
  });

  it("never reports a position off the top or the left, which cannot be seen", () => {
    const { onMoveNode } = renderCanvas();
    firePointer(nodeGroup("cond_1"), "pointerdown", { clientX: 0, clientY: 0 });
    firePointer(window, "pointermove", { clientX: -4000, clientY: -4000 });
    firePointer(window, "pointerup", {});
    expect(onMoveNode).toHaveBeenCalledWith("cond_1", 0, 0);
  });

  it("treats a click that did not move as a selection, not a move", () => {
    const { onMoveNode, onSelectNode } = renderCanvas();
    const group = nodeGroup("reg_1");
    firePointer(group, "pointerdown", { clientX: 10, clientY: 10 });
    firePointer(window, "pointermove", { clientX: 11, clientY: 11 });
    firePointer(window, "pointerup", {});
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onMoveNode).not.toHaveBeenCalled();
    expect(onSelectNode).toHaveBeenCalledWith("reg_1");
  });

  it("does not select the node the author just dragged", () => {
    const { onSelectNode } = renderCanvas();
    const group = nodeGroup("reg_1");
    firePointer(group, "pointerdown", { clientX: 10, clientY: 10 });
    firePointer(window, "pointermove", { clientX: 200, clientY: 200 });
    firePointer(window, "pointerup", {});
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onSelectNode).not.toHaveBeenCalled();
  });

  it("drags nothing on a tree the caller may not edit", () => {
    const { onSelectNode } = renderCanvas({ onMoveNode: undefined });
    const group = nodeGroup("reg_1");
    firePointer(group, "pointerdown", { clientX: 10, clientY: 10 });
    firePointer(window, "pointermove", { clientX: 200, clientY: 200 });
    firePointer(window, "pointerup", {});
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    // The click still selects: a read-only canvas is still readable.
    expect(onSelectNode).toHaveBeenCalledWith("reg_1");
  });
});

describe("<BetaCanvas> stop node", () => {
  it("draws the stop as a circle and every other kind as a box", () => {
    renderCanvas();
    expect(nodeGroup("stop_1").getAttribute("data-shape")).toBe("circle");
    expect(nodeGroup("reg_1").getAttribute("data-shape")).toBeNull();
    expect(nodeGroup("stop_1").querySelector("circle")).not.toBeNull();
  });
});

describe("<BetaCanvas> reset layout", () => {
  it("offers the button only once a node carries a position", () => {
    renderCanvas();
    expect(screen.queryByRole("button", { name: "Back to automatic layout" })).toBeNull();
  });

  it("shows it when one does", () => {
    renderCanvas({
      layout: layoutBetaTree(
        parseBetaDoc(YAML.replace("  reg_1:\n", "  reg_1:\n    ui: { x: 400, y: 300 }\n")),
      ),
    });
    expect(screen.getByRole("button", { name: "Back to automatic layout" })).toBeInTheDocument();
  });
});

describe("<BetaCanvas> condition body", () => {
  it("counts a group's tests instead of reading it as nothing", () => {
    const grouped = YAML.replace(
      "      tree: { op: lt, left: { source: indices, index_code: ndmi, key: baseline_deviation }, right: -0.1 }",
      "      tree: { all_of: [ { op: lt, left: { source: indices }, right: 0 }, { op: gt, left: { source: block }, right: 1 } ] }",
    );
    renderCanvas({ layout: layoutBetaTree(parseBetaDoc(grouped)) });
    expect(screen.getByText("all of 2")).toBeInTheDocument();
  });
});
