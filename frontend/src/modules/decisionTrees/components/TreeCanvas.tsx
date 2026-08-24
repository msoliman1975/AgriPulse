// SVG renderer for a compiled decision tree.
//
// PR-D1 made it read-only. PR-D2 added click-to-select + dirty
// indicators. PR-D4 added `+` ports for adding children to empty
// branches. PR-D6 turned every branch port into a drag source so the
// author can rewire connections by dragging from a port to a target
// node. PR-D8 adds the controls a 30-40 node tree needs: zoom, pan,
// drag a box to place it by hand, drag the canvas taller, fit to
// screen, and export a PNG.
//
// Two coordinate systems:
//   * world  — the px coordinates `treeLayout` assigns. Everything
//     inside <g data-tree-world> is drawn in world units.
//   * screen — px inside the canvas viewport <div>. `toWorld()`
//     converts a pointer event to world units from the container rect
//     and the current transform, so every drag stays correct at any
//     zoom level. (We do not use getScreenCTM: the plain arithmetic is
//     exact for our single translate+scale and works under test.)
//
// Three drag sources share the surface. Each stops propagation on
// pointerdown so they never fight:
//   * a branch PORT  -> rewire the branch (PR-D6).
//   * a node BOX     -> move the box (manual layout, browser-local).
//   * the BACKGROUND -> pan the canvas.
// None of them counts as a drag until the pointer has moved
// DRAG_THRESHOLD_PX; below that it stays a click (add child / select /
// deselect).

import {
  useRef,
  useState,
  useEffect,
  useMemo,
  useCallback,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useTranslation } from "react-i18next";

import type { LayoutResult, PositionedNode } from "../layout/treeLayout";
import { LAYOUT_CONSTANTS } from "../layout/treeLayout";
import {
  IDENTITY_VIEWPORT,
  ZOOM_STEP,
  fitToViewport,
  zoomAt,
  zoomAtCentre,
  zoomPercent,
  type Viewport,
} from "../lib/canvasViewport";
import { exportCanvasPng } from "../lib/exportCanvasPng";
import { localizedField } from "@/lib/localizedField";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";

const { NODE_WIDTH, NODE_HEIGHT } = LAYOUT_CONSTANTS;
const DRAG_THRESHOLD_PX = 4;
/** Arrow-key pan step, in screen px. */
const KEY_PAN_PX = 48;

interface TreeCanvasProps {
  layout: LayoutResult;
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string | null) => void;
  dirtyNodeIds?: ReadonlySet<string>;
  /** PR-D4: click on a `+` port -> add a child. */
  onAddChild?: (parentId: string, branch: "match" | "miss") => void;
  /** PR-D6: drag from any port to a node -> rewire the branch. */
  onRewire?: (parentId: string, branch: "match" | "miss", targetId: string) => void;
  /** PR-D7: dry-run path overlay. Visited nodes get a halo; edges
   *  along the path render thicker. `terminalNodeId` is the leaf at
   *  the end of the path — drawn with the strongest emphasis. */
  pathNodeIds?: ReadonlySet<string>;
  pathEdgeKeys?: ReadonlySet<string>;
  terminalNodeId?: string | null;
  /** PR-D8: canvas viewport height in px; the author drags the grip
   *  at the bottom to change it. */
  height: number;
  onHeightChange: (height: number) => void;
  /** PR-D8: called while a box is dragged. Undefined turns box
   *  dragging off. Coordinates are world units, top-left of the box. */
  onNodeMove?: (nodeId: string, x: number, y: number) => void;
  /** PR-D8: drop every hand-placed position and go back to the
   *  auto-layout. */
  onResetLayout?: () => void;
  canResetLayout?: boolean;
  /** File name used by the PNG export. */
  exportFileName?: string;
}

interface DragState {
  parentId: string;
  branch: "match" | "miss";
  /** Port origin in world coords (where the dashed line starts). */
  originX: number;
  originY: number;
  cursorX: number;
  cursorY: number;
  hoverNodeId: string | null;
  moved: boolean;
}

interface NodeDragState {
  nodeId: string;
  /** Cursor offset inside the box, in world units, so the box does not
   *  jump to centre itself under the cursor. */
  offsetX: number;
  offsetY: number;
  moved: boolean;
}

interface PanState {
  startScreenX: number;
  startScreenY: number;
  originTx: number;
  originTy: number;
  moved: boolean;
}

interface ResizeState {
  startClientY: number;
  startHeight: number;
}

export function TreeCanvas({
  layout,
  selectedNodeId = null,
  onSelectNode,
  dirtyNodeIds,
  onAddChild,
  onRewire,
  pathNodeIds,
  pathEdgeKeys,
  terminalNodeId,
  height,
  onHeightChange,
  onNodeMove,
  onResetLayout,
  canResetLayout = false,
  exportFileName = "decision-tree.png",
}: TreeCanvasProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const worldRef = useRef<SVGGElement | null>(null);

  const [view, setView] = useState<Viewport>(IDENTITY_VIEWPORT);
  const viewRef = useRef(view);
  viewRef.current = view;

  const [drag, setDrag] = useState<DragState | null>(null);
  const [nodeDrag, setNodeDrag] = useState<NodeDragState | null>(null);
  const [pan, setPan] = useState<PanState | null>(null);
  const [resize, setResize] = useState<ResizeState | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  // Set on the pointerup that ends a real drag, read (and cleared) by
  // the click handler that would otherwise fire straight after.
  const suppressNodeClickRef = useRef(false);
  const suppressBackgroundClickRef = useRef(false);

  const viewportSize = useCallback((): { width: number; height: number } => {
    const el = containerRef.current;
    if (!el) return { width: 0, height: 0 };
    const rect = el.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }, []);

  /** Pointer event -> world coords. Null when the container is not
   *  mounted yet. */
  const toWorld = useCallback(
    (evt: { clientX: number; clientY: number }): { x: number; y: number } | null => {
      const el = containerRef.current;
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const v = viewRef.current;
      return {
        x: (evt.clientX - rect.left - v.tx) / v.scale,
        y: (evt.clientY - rect.top - v.ty) / v.scale,
      };
    },
    [],
  );

  const fitToScreen = useCallback(() => {
    const size = viewportSize();
    if (size.width === 0 || size.height === 0) return;
    setView(fitToViewport({ width: layout.width, height: layout.height }, size));
  }, [layout.width, layout.height, viewportSize]);

  // Fit once, when the graph first has something to show. After that
  // the view is the author's to move; re-fitting on every edit would
  // pull the canvas out from under them.
  const didAutoFitRef = useRef(false);
  useEffect(() => {
    if (didAutoFitRef.current) return;
    if (layout.nodes.length === 0) return;
    const size = viewportSize();
    if (size.width === 0 || size.height === 0) return;
    didAutoFitRef.current = true;
    fitToScreen();
  }, [layout.nodes.length, fitToScreen, viewportSize]);

  // Ctrl/Cmd + wheel zooms about the cursor. A plain wheel is left
  // alone so the page still scrolls when the pointer is over the
  // canvas. Registered natively because the listener must be
  // non-passive to call preventDefault.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (evt: WheelEvent): void => {
      if (!evt.ctrlKey && !evt.metaKey) return;
      evt.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = Math.exp(-evt.deltaY * 0.002);
      setView((v) => zoomAt(v, factor, evt.clientX - rect.left, evt.clientY - rect.top));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // ---- Port drag (rewire) — PR-D6 ---------------------------------

  useEffect(() => {
    if (!drag) return;
    const onMove = (evt: PointerEvent): void => {
      const local = toWorld(evt);
      if (!local) return;
      setDrag((prev) => {
        if (!prev) return null;
        const dx = Math.abs(local.x - prev.cursorX);
        const dy = Math.abs(local.y - prev.cursorY);
        return {
          ...prev,
          cursorX: local.x,
          cursorY: local.y,
          moved: prev.moved || dx + dy > DRAG_THRESHOLD_PX,
        };
      });
    };
    const onUp = (): void => {
      // pointerup is handled by the per-node handler below if dropped
      // on a node; if not, just cancel. We need to delay-clear so the
      // per-node handler runs first.
      setTimeout(() => setDrag(null), 0);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [drag, toWorld]);

  const onPortPointerDown = (
    parentId: string,
    branch: "match" | "miss",
    originX: number,
    originY: number,
    evt: ReactPointerEvent<SVGGElement>,
  ): void => {
    const local = toWorld(evt);
    if (!local) return;
    evt.stopPropagation();
    setDrag({
      parentId,
      branch,
      originX,
      originY,
      cursorX: local.x,
      cursorY: local.y,
      hoverNodeId: null,
      moved: false,
    });
  };

  const onPortClick = (parentId: string, branch: "match" | "miss"): void => {
    onAddChild?.(parentId, branch);
  };

  // ---- Node drag (manual layout) — PR-D8 --------------------------

  useEffect(() => {
    if (!nodeDrag || !onNodeMove) return;
    const onMove = (evt: PointerEvent): void => {
      const local = toWorld(evt);
      if (!local) return;
      const nextX = Math.max(0, Math.round(local.x - nodeDrag.offsetX));
      const nextY = Math.max(0, Math.round(local.y - nodeDrag.offsetY));
      onNodeMove(nodeDrag.nodeId, nextX, nextY);
      if (!nodeDrag.moved) {
        setNodeDrag((prev) => (prev ? { ...prev, moved: true } : prev));
      }
    };
    const onUp = (): void => {
      if (nodeDrag.moved) suppressNodeClickRef.current = true;
      setNodeDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [nodeDrag, onNodeMove, toWorld]);

  const onNodePointerDown = (node: PositionedNode, evt: ReactPointerEvent<SVGGElement>): void => {
    if (!onNodeMove) return;
    if (evt.button !== 0) return;
    const local = toWorld(evt);
    if (!local) return;
    // Keep the pan handler on the background from also firing.
    evt.stopPropagation();
    setNodeDrag({
      nodeId: node.id,
      offsetX: local.x - node.x,
      offsetY: local.y - node.y,
      moved: false,
    });
  };

  const onNodeClick = (nodeId: string | null): void => {
    if (suppressNodeClickRef.current) {
      suppressNodeClickRef.current = false;
      return;
    }
    onSelectNode?.(nodeId);
  };

  // ---- Background pan — PR-D8 -------------------------------------

  useEffect(() => {
    if (!pan) return;
    const onMove = (evt: PointerEvent): void => {
      const dx = evt.clientX - pan.startScreenX;
      const dy = evt.clientY - pan.startScreenY;
      setView((v) => ({ ...v, tx: pan.originTx + dx, ty: pan.originTy + dy }));
      if (!pan.moved && Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD_PX) {
        setPan((prev) => (prev ? { ...prev, moved: true } : prev));
      }
    };
    const onUp = (): void => {
      if (pan.moved) suppressBackgroundClickRef.current = true;
      setPan(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [pan]);

  const onBackgroundPointerDown = (evt: ReactPointerEvent<SVGSVGElement>): void => {
    if (evt.button !== 0) return;
    const v = viewRef.current;
    setPan({
      startScreenX: evt.clientX,
      startScreenY: evt.clientY,
      originTx: v.tx,
      originTy: v.ty,
      moved: false,
    });
  };

  const onBackgroundClick = (): void => {
    if (suppressBackgroundClickRef.current) {
      suppressBackgroundClickRef.current = false;
      return;
    }
    onSelectNode?.(null);
  };

  // ---- Canvas height grip — PR-D8 ---------------------------------

  useEffect(() => {
    if (!resize) return;
    const onMove = (evt: PointerEvent): void => {
      onHeightChange(resize.startHeight + (evt.clientY - resize.startClientY));
    };
    const onUp = (): void => setResize(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [resize, onHeightChange]);

  const onGripPointerDown = (evt: ReactPointerEvent<HTMLButtonElement>): void => {
    if (evt.button !== 0) return;
    evt.preventDefault();
    setResize({ startClientY: evt.clientY, startHeight: height });
  };

  const onGripKeyDown = (evt: ReactKeyboardEvent<HTMLButtonElement>): void => {
    if (evt.key === "ArrowDown") {
      evt.preventDefault();
      onHeightChange(height + KEY_PAN_PX);
    } else if (evt.key === "ArrowUp") {
      evt.preventDefault();
      onHeightChange(height - KEY_PAN_PX);
    }
  };

  // ---- Keyboard ----------------------------------------------------

  const onCanvasKeyDown = (evt: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (evt.key === "+" || evt.key === "=") {
      evt.preventDefault();
      setView((v) => zoomAtCentre(v, ZOOM_STEP, viewportSize()));
    } else if (evt.key === "-" || evt.key === "_") {
      evt.preventDefault();
      setView((v) => zoomAtCentre(v, 1 / ZOOM_STEP, viewportSize()));
    } else if (evt.key === "0") {
      evt.preventDefault();
      fitToScreen();
    } else if (evt.key === "ArrowLeft") {
      evt.preventDefault();
      setView((v) => ({ ...v, tx: v.tx + KEY_PAN_PX }));
    } else if (evt.key === "ArrowRight") {
      evt.preventDefault();
      setView((v) => ({ ...v, tx: v.tx - KEY_PAN_PX }));
    } else if (evt.key === "ArrowUp") {
      evt.preventDefault();
      setView((v) => ({ ...v, ty: v.ty + KEY_PAN_PX }));
    } else if (evt.key === "ArrowDown") {
      evt.preventDefault();
      setView((v) => ({ ...v, ty: v.ty - KEY_PAN_PX }));
    }
  };

  // ---- PNG export --------------------------------------------------

  const onExportPng = (): void => {
    const world = worldRef.current;
    if (!world) return;
    setExportError(null);
    void exportCanvasPng(
      world,
      { width: layout.width, height: layout.height },
      exportFileName,
    ).catch(() => setExportError(t("editor.canvas.exportFailed")));
  };

  // ---- Drop-target bookkeeping (PR-D6) -----------------------------

  const validDropTargets = useMemo(() => {
    if (!drag) return null;
    const set = new Set<string>();
    for (const n of layout.nodes) {
      if (n.id !== drag.parentId) set.add(n.id);
    }
    return set;
  }, [drag, layout.nodes]);

  const onNodePointerEnter = (nodeId: string): void => {
    setDrag((prev) => (prev ? { ...prev, hoverNodeId: nodeId } : null));
  };
  const onNodePointerLeave = (nodeId: string): void => {
    setDrag((prev) =>
      prev && prev.hoverNodeId === nodeId ? { ...prev, hoverNodeId: null } : prev,
    );
  };
  const onNodePointerUp = (nodeId: string): void => {
    const d = drag;
    if (!d || !d.moved) return;
    if (d.parentId === nodeId) return;
    onRewire?.(d.parentId, d.branch, nodeId);
    setDrag(null);
  };

  if (layout.nodes.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ap-line p-8 text-center text-sm text-ap-muted">
        {t("viewer.emptyTree")}
      </p>
    );
  }

  const canShowPorts = onAddChild !== undefined || onRewire !== undefined;
  const canvasCursor = pan ? "grabbing" : "grab";

  return (
    <Card noPadding className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-ap-line px-2 py-1.5">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setView((v) => zoomAtCentre(v, 1 / ZOOM_STEP, viewportSize()))}
          title={t("editor.canvas.zoomOut")}
          aria-label={t("editor.canvas.zoomOut")}
        >
          <span aria-hidden="true">-</span>
        </Button>
        <span className="w-12 text-center text-xs tabular-nums text-ap-muted">
          {zoomPercent(view)}%
        </span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setView((v) => zoomAtCentre(v, ZOOM_STEP, viewportSize()))}
          title={t("editor.canvas.zoomIn")}
          aria-label={t("editor.canvas.zoomIn")}
        >
          <span aria-hidden="true">+</span>
        </Button>
        <Button size="sm" variant="secondary" onClick={fitToScreen}>
          {t("editor.canvas.fit")}
        </Button>
        {onResetLayout ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={onResetLayout}
            disabled={!canResetLayout}
            title={t("editor.canvas.resetLayoutHint")}
          >
            {t("editor.canvas.resetLayout")}
          </Button>
        ) : null}
        <Button size="sm" variant="secondary" onClick={onExportPng}>
          {t("editor.canvas.exportPng")}
        </Button>
        <span className="ms-auto text-[11px] text-ap-muted">
          {t("editor.canvas.nodeCount", { count: layout.nodes.length })} · {t("editor.canvas.hint")}
        </span>
      </div>
      {exportError ? (
        <p className="border-b border-ap-line bg-ap-crit/5 px-3 py-1.5 text-xs text-ap-crit">
          {exportError}
        </p>
      ) : null}
      {/* The canvas is a focusable drawing surface: it takes the zoom
          and pan shortcuts, so it needs a tabIndex and a key handler
          that the a11y rules do not expect on a div. */}
      {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      <div
        ref={containerRef}
        dir="ltr"
        tabIndex={0}
        role="application"
        aria-label={t("viewer.svgAria")}
        onKeyDown={onCanvasKeyDown}
        className="relative overflow-hidden bg-ap-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ap-primary"
        style={{ height, touchAction: "none" }}
      >
        <svg
          width="100%"
          height="100%"
          className="block select-none"
          style={{ cursor: canvasCursor }}
          onPointerDown={onBackgroundPointerDown}
          onClick={onSelectNode ? onBackgroundClick : undefined}
        >
          <g
            ref={worldRef}
            data-tree-world=""
            transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}
          >
            {layout.edges.map((edge) => {
              const key = `${edge.from}->${edge.to}-${edge.branch}`;
              return (
                <EdgePath key={key} edge={edge} t={t} onPath={pathEdgeKeys?.has(key) ?? false} />
              );
            })}
            {layout.nodes.map((node) => (
              <NodeRect
                key={node.id}
                node={node}
                selected={selectedNodeId === node.id}
                dirty={dirtyNodeIds?.has(node.id) ?? false}
                isDropTarget={
                  drag !== null &&
                  drag.moved &&
                  validDropTargets?.has(node.id) === true &&
                  drag.hoverNodeId === node.id
                }
                isDropEligible={
                  drag !== null && drag.moved && validDropTargets?.has(node.id) === true
                }
                onPath={pathNodeIds?.has(node.id) ?? false}
                isTerminal={terminalNodeId === node.id}
                movable={onNodeMove !== undefined}
                moving={nodeDrag?.nodeId === node.id && nodeDrag.moved}
                onClick={onSelectNode ? onNodeClick : undefined}
                onPointerDown={(evt) => onNodePointerDown(node, evt)}
                onPointerEnter={() => onNodePointerEnter(node.id)}
                onPointerLeave={() => onNodePointerLeave(node.id)}
                onPointerUp={() => onNodePointerUp(node.id)}
              />
            ))}
            {canShowPorts
              ? layout.nodes.flatMap((node) => {
                  if (node.role !== "decision") return [];
                  const data = node.data;
                  const ports: JSX.Element[] = [];
                  const matchFilled = Boolean(data.on_match);
                  const missFilled = Boolean(data.on_miss);
                  ports.push(
                    <BranchPort
                      key={`${node.id}-port-match`}
                      parentId={node.id}
                      branch="match"
                      filled={matchFilled}
                      nodeX={node.x}
                      nodeY={node.y}
                      onClick={() => onPortClick(node.id, "match")}
                      onPointerDown={(originX, originY, evt) =>
                        onPortPointerDown(node.id, "match", originX, originY, evt)
                      }
                    />,
                  );
                  ports.push(
                    <BranchPort
                      key={`${node.id}-port-miss`}
                      parentId={node.id}
                      branch="miss"
                      filled={missFilled}
                      nodeX={node.x}
                      nodeY={node.y}
                      onClick={() => onPortClick(node.id, "miss")}
                      onPointerDown={(originX, originY, evt) =>
                        onPortPointerDown(node.id, "miss", originX, originY, evt)
                      }
                    />,
                  );
                  return ports;
                })
              : null}
            {/* PR-D6: live drag indicator — dashed line from port to cursor.
                Only renders once the cursor has moved past the threshold so
                a click does not briefly flash a line. */}
            {drag && drag.moved ? (
              <line
                x1={drag.originX}
                y1={drag.originY}
                x2={drag.cursorX}
                y2={drag.cursorY}
                stroke={drag.branch === "match" ? "#16a34a" : "#94a3b8"}
                strokeWidth={2}
                strokeDasharray="5 4"
                pointerEvents="none"
              />
            ) : null}
          </g>
        </svg>
      </div>
      {/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      {/* A real <button> so it is focusable and announced without a
          hand-rolled tabIndex. Pointer drag changes the height; the
          up/down arrows do the same from the keyboard. */}
      <button
        type="button"
        aria-label={t("editor.canvas.resizeGrip")}
        onPointerDown={onGripPointerDown}
        onKeyDown={onGripKeyDown}
        className="flex h-3 w-full cursor-ns-resize items-center justify-center border-t border-ap-line bg-ap-panel hover:bg-ap-line/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ap-primary"
      >
        <span className="h-0.5 w-10 rounded-full bg-ap-line" aria-hidden="true" />
      </button>
    </Card>
  );
}

// ---- Edge ----------------------------------------------------------

interface EdgePathProps {
  edge: LayoutResult["edges"][number];
  t: ReturnType<typeof useTranslation>["t"];
  /** PR-D7: edge is on the dry-run path → thicker stroke + saturated color. */
  onPath?: boolean;
}

function EdgePath({ edge, t, onPath = false }: EdgePathProps): JSX.Element {
  const dx = edge.toX - edge.fromX;
  const dy = edge.toY - edge.fromY;
  const c1x = edge.fromX;
  const c1y = edge.fromY + dy * 0.5;
  const c2x = edge.toX;
  const c2y = edge.toY - dy * 0.5;
  const d = `M ${edge.fromX} ${edge.fromY} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${edge.toX} ${edge.toY}`;

  const isMatch = edge.branch === "match";
  const stroke = isMatch ? "#16a34a" : "#94a3b8";
  const label = isMatch ? t("viewer.edges.match") : t("viewer.edges.miss");

  const midX = (edge.fromX + edge.toX) / 2 + (dx >= 0 ? 8 : -8);
  const midY = (edge.fromY + edge.toY) / 2;

  return (
    <g>
      <path
        d={d}
        stroke={stroke}
        strokeWidth={onPath ? 4 : 2}
        strokeDasharray={isMatch ? undefined : onPath ? "8 3" : "5 4"}
        fill="none"
        opacity={onPath ? 1 : 0.85}
      />
      <text
        x={midX}
        y={midY}
        fontSize={11}
        fill={stroke}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        dominantBaseline="middle"
        textAnchor={dx >= 0 ? "start" : "end"}
      >
        {label}
      </text>
    </g>
  );
}

// ---- Node ----------------------------------------------------------

interface NodeRectProps {
  node: PositionedNode;
  selected: boolean;
  dirty: boolean;
  isDropTarget: boolean;
  isDropEligible: boolean;
  /** PR-D7: node is on the dry-run path → subtle highlight halo. */
  onPath: boolean;
  /** PR-D7: terminal node (last on the path) → strong highlight. */
  isTerminal: boolean;
  /** PR-D8: the box can be dragged to a hand-picked position. */
  movable: boolean;
  /** PR-D8: this box is the one being dragged right now. */
  moving: boolean;
  onClick?: (nodeId: string | null) => void;
  onPointerDown: (evt: ReactPointerEvent<SVGGElement>) => void;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onPointerUp: () => void;
}

function NodeRect({
  node,
  selected,
  dirty,
  isDropTarget,
  isDropEligible,
  onPath,
  isTerminal,
  movable,
  moving,
  onClick,
  onPointerDown,
  onPointerEnter,
  onPointerLeave,
  onPointerUp,
}: NodeRectProps): JSX.Element {
  const { x, y, role, data } = node;
  const palette = paletteFor(role);
  const clipId = `tree-node-clip-${nodeIdToken(node.id)}`;
  const isInteractive = onClick !== undefined;
  const cursor = moving ? "grabbing" : movable ? "grab" : isInteractive ? "pointer" : "default";
  // During a drag, dim nodes that aren't eligible drop targets to
  // signal where the user can release. The drop target itself gets a
  // bold highlight ring.
  const opacity = isDropEligible || !isDropTargetMode(isDropTarget, isDropEligible) ? 1 : 0.4;
  return (
    <g
      onClick={
        onClick
          ? (event) => {
              event.stopPropagation();
              onClick(node.id);
            }
          : undefined
      }
      onPointerDown={onPointerDown}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      onPointerUp={onPointerUp}
      style={{ cursor, opacity }}
    >
      {selected ? (
        <rect
          x={x - 4}
          y={y - 4}
          width={NODE_WIDTH + 8}
          height={NODE_HEIGHT + 8}
          rx={12}
          ry={12}
          fill="none"
          stroke="#2563eb"
          strokeWidth={2.5}
          strokeDasharray="6 3"
        />
      ) : null}
      {isDropTarget ? (
        <rect
          x={x - 6}
          y={y - 6}
          width={NODE_WIDTH + 12}
          height={NODE_HEIGHT + 12}
          rx={14}
          ry={14}
          fill="#16a34a22"
          stroke="#16a34a"
          strokeWidth={3}
        />
      ) : null}
      {onPath && !isDropTarget ? (
        <rect
          x={x - 3}
          y={y - 3}
          width={NODE_WIDTH + 6}
          height={NODE_HEIGHT + 6}
          rx={12}
          ry={12}
          fill={isTerminal ? "#facc1533" : "#fde04822"}
          stroke={isTerminal ? "#ca8a04" : "#facc15"}
          strokeWidth={isTerminal ? 3 : 2}
        />
      ) : null}
      <rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={10}
        ry={10}
        fill={palette.bg}
        stroke={palette.border}
        strokeWidth={1.5}
      />
      {/* Everything with text is clipped to the box. A label longer
          than the box, in any language, is cut at the edge instead of
          painting over the neighbouring boxes. The clipPath lives
          inside this <g> so the PNG export, which clones only the
          world group, keeps it. */}
      <clipPath id={clipId}>
        <rect x={x} y={y} width={NODE_WIDTH} height={NODE_HEIGHT} rx={10} ry={10} />
      </clipPath>
      <g clipPath={`url(#${clipId})`}>
        <text
          x={x + 12}
          y={y + 16}
          fontSize={10}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fill={palette.dim}
        >
          {node.id}
        </text>
        <RoleChip x={x + NODE_WIDTH - 90} y={y + 8} role={role} data={data} />
        {role === "decision" ? (
          <DecisionBody x={x} y={y} data={data} />
        ) : (
          <LeafBody x={x} y={y} role={role} data={data} />
        )}
      </g>
      {dirty ? (
        <circle cx={x + NODE_WIDTH - 12} cy={y + NODE_HEIGHT - 12} r={4} fill="#2563eb" />
      ) : null}
    </g>
  );
}

function isDropTargetMode(isDropTarget: boolean, isDropEligible: boolean): boolean {
  return isDropTarget || isDropEligible;
}

// ---- Branch port (PR-D4 + PR-D6) ----------------------------------

interface BranchPortProps {
  parentId: string;
  branch: "match" | "miss";
  /** Whether the branch already has a child. Filled ports show a
   *  rewire glyph (·); empty ports show a `+`. Click only adds when
   *  the branch is empty. */
  filled: boolean;
  nodeX: number;
  nodeY: number;
  onClick: () => void;
  onPointerDown: (originX: number, originY: number, evt: ReactPointerEvent<SVGGElement>) => void;
}

function BranchPort({
  branch,
  filled,
  nodeX,
  nodeY,
  onClick,
  onPointerDown,
}: BranchPortProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const isMatch = branch === "match";
  const cx = isMatch ? nodeX + 60 : nodeX + NODE_WIDTH - 60;
  const cy = nodeY + NODE_HEIGHT + 18;
  const stroke = isMatch ? "#16a34a" : "#94a3b8";
  const fill = filled ? stroke : "#ffffff";
  const title = filled
    ? isMatch
      ? t("editor.canvas.dragMatch")
      : t("editor.canvas.dragMiss")
    : isMatch
      ? t("editor.canvas.addMatch")
      : t("editor.canvas.addMiss");
  return (
    <g
      style={{ cursor: filled ? "grab" : "pointer" }}
      onPointerDown={(evt) => onPointerDown(cx, cy, evt)}
      onClick={(evt) => {
        evt.stopPropagation();
        if (!filled) onClick();
      }}
    >
      <title>{title}</title>
      <circle cx={cx} cy={cy} r={11} fill={fill} stroke={stroke} strokeWidth={1.5} />
      {filled ? (
        // "↻" rewire glyph — a small open arc that reads as "swap"
        // without the rotation animation a real ↻ would imply.
        <path
          d={`M ${cx - 4} ${cy - 1} a 4 4 0 1 0 4 -4`}
          fill="none"
          stroke="#ffffff"
          strokeWidth={1.5}
        />
      ) : (
        <>
          <line x1={cx - 5} y1={cy} x2={cx + 5} y2={cy} stroke={stroke} strokeWidth={1.75} />
          <line x1={cx} y1={cy - 5} x2={cx} y2={cy + 5} stroke={stroke} strokeWidth={1.75} />
        </>
      )}
    </g>
  );
}

// ---- Decision / Leaf bodies (unchanged) ---------------------------

function DecisionBody({
  x,
  y,
  data,
}: {
  x: number;
  y: number;
  data: PositionedNode["data"];
}): JSX.Element {
  const { t, i18n } = useTranslation("decisionTrees");
  const summary =
    localizedField(i18n.language, data.label_en ?? null, data.label_ar ?? null) ||
    t("viewer.body.unlabelledDecision");
  return (
    <>
      <text x={x + 12} y={y + 42} fontSize={13} fontWeight={600} fill="#0f172a">
        {t("viewer.body.decision")}
      </text>
      <text x={x + 12} y={y + 64} fontSize={12} fill="#475569">
        {truncate(summary, 32)}
      </text>
    </>
  );
}

function LeafBody({
  x,
  y,
  role,
  data,
}: {
  x: number;
  y: number;
  role: PositionedNode["role"];
  data: PositionedNode["data"];
}): JSX.Element {
  const { i18n } = useTranslation("decisionTrees");
  const outcome = data.outcome ?? {};
  const actionType = outcome.action_type ?? "—";
  // The outcome text wins over the node label, and each pair picks its
  // own language. Resolving the pair first, then falling back, keeps a
  // node with an Arabic outcome text and an English label readable.
  const text =
    localizedField(i18n.language, outcome.text_en ?? null, outcome.text_ar ?? null) ||
    localizedField(i18n.language, data.label_en ?? null, data.label_ar ?? null) ||
    "";
  void role;
  return (
    <>
      <text x={x + 12} y={y + 42} fontSize={13} fontWeight={600} fill="#0f172a">
        {actionType}
      </text>
      <text x={x + 12} y={y + 64} fontSize={12} fill="#475569">
        {truncate(text, 36)}
      </text>
    </>
  );
}

function RoleChip({
  x,
  y,
  role,
  data,
}: {
  x: number;
  y: number;
  role: PositionedNode["role"];
  data: PositionedNode["data"];
}): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const palette = paletteFor(role);
  let text: string;
  if (role === "decision") {
    text = t("viewer.chips.decision");
  } else if (role === "leaf-alert") {
    text = (data.outcome?.severity ?? "alert").toString();
  } else if (role === "leaf-recommendation") {
    const c = data.outcome?.confidence;
    text =
      c !== undefined
        ? `${t("viewer.chips.recommendation")} · ${c}`
        : t("viewer.chips.recommendation");
  } else {
    text = t("viewer.chips.noop");
  }
  return (
    <>
      <rect
        x={x}
        y={y}
        width={82}
        height={20}
        rx={10}
        ry={10}
        fill={palette.chipBg}
        stroke={palette.chipBorder}
        strokeWidth={1}
      />
      <text
        x={x + 41}
        y={y + 14}
        fontSize={10}
        fontWeight={600}
        fill={palette.chipText}
        textAnchor="middle"
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
      >
        {truncate(text, 11)}
      </text>
    </>
  );
}

// ---- Helpers -------------------------------------------------------

interface Palette {
  bg: string;
  border: string;
  dim: string;
  chipBg: string;
  chipBorder: string;
  chipText: string;
}

function paletteFor(role: PositionedNode["role"]): Palette {
  switch (role) {
    case "leaf-alert":
      return {
        bg: "#fffbeb",
        border: "#f59e0b",
        dim: "#92400e",
        chipBg: "#fde68a",
        chipBorder: "#f59e0b",
        chipText: "#7c2d12",
      };
    case "leaf-recommendation":
      return {
        bg: "#ecfdf5",
        border: "#10b981",
        dim: "#065f46",
        chipBg: "#a7f3d0",
        chipBorder: "#10b981",
        chipText: "#065f46",
      };
    case "leaf-noop":
      return {
        bg: "#f8fafc",
        border: "#cbd5e1",
        dim: "#64748b",
        chipBg: "#e2e8f0",
        chipBorder: "#cbd5e1",
        chipText: "#475569",
      };
    case "decision":
    default:
      return {
        bg: "#ffffff",
        border: "#94a3b8",
        dim: "#475569",
        chipBg: "#e0e7ff",
        chipBorder: "#6366f1",
        chipText: "#3730a3",
      };
  }
}

/** Make a node id safe to use inside an SVG id and a url(#…) reference.
 *  Node ids come from the YAML, so they can hold characters that break
 *  the reference. Covered through the rendered DOM in TreeCanvas.test. */
function nodeIdToken(id: string): string {
  const token = id.replace(/[^A-Za-z0-9_-]/g, "_");
  return token || "node";
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}
