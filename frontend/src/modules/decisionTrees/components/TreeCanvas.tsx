// SVG renderer for a compiled decision tree.
//
// PR-D1 made it read-only. PR-D2 added click-to-select + dirty
// indicators. PR-D4 added `+` ports for adding children to empty
// branches. PR-D6 turns every branch port into a drag source so the
// author can rewire connections by dragging from a port to a target
// node.
//
// Drag UX:
//   - pointerdown on a port enters "potential drag" — if the cursor
//     moves more than DRAG_THRESHOLD before pointerup, it's a drag;
//     otherwise the port's click handler fires (= add-child for empty
//     ports, no-op for filled ports).
//   - pointermove tracks the cursor in SVG coords and re-renders a
//     dashed line from the source port to the cursor.
//   - pointerup on a node calls `onRewire(parent, branch, target)`.

import { useRef, useState, useEffect, useMemo, type PointerEvent as ReactPointerEvent } from "react";
import { useTranslation } from "react-i18next";

import type { LayoutResult, PositionedNode } from "../layout/treeLayout";
import { LAYOUT_CONSTANTS } from "../layout/treeLayout";

const { NODE_WIDTH, NODE_HEIGHT } = LAYOUT_CONSTANTS;
const DRAG_THRESHOLD_PX = 4;

interface TreeCanvasProps {
  layout: LayoutResult;
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string | null) => void;
  dirtyNodeIds?: ReadonlySet<string>;
  /** PR-D4: click on a `+` port → add a child. */
  onAddChild?: (parentId: string, branch: "match" | "miss") => void;
  /** PR-D6: drag from any port to a node → rewire the branch. */
  onRewire?: (parentId: string, branch: "match" | "miss", targetId: string) => void;
  /** PR-D7: dry-run path overlay. Visited nodes get a halo; edges
   *  along the path render thicker. `terminalNodeId` is the leaf at
   *  the end of the path — drawn with the strongest emphasis. */
  pathNodeIds?: ReadonlySet<string>;
  pathEdgeKeys?: ReadonlySet<string>;
  terminalNodeId?: string | null;
}

interface DragState {
  parentId: string;
  branch: "match" | "miss";
  /** Port origin in SVG coords (where the dashed line starts). */
  originX: number;
  originY: number;
  cursorX: number;
  cursorY: number;
  hoverNodeId: string | null;
  moved: boolean;
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
}: TreeCanvasProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);

  // Convert a pointer event to SVG-local coords. Uses the SVG element's
  // current CTM so it stays correct under scroll / scale.
  function clientToSvg(evt: { clientX: number; clientY: number }): { x: number; y: number } | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const inv = ctm.inverse();
    const local = pt.matrixTransform(inv);
    return { x: local.x, y: local.y };
  }

  // Pointer-move on window during a drag — using window so the user
  // can drag outside the SVG bounds without losing the drag.
  useEffect(() => {
    if (!drag) return;
    const onMove = (evt: PointerEvent): void => {
      const local = clientToSvg(evt);
      if (!local) return;
      const dx = Math.abs(local.x - drag.cursorX);
      const dy = Math.abs(local.y - drag.cursorY);
      setDrag((prev) =>
        prev
          ? {
              ...prev,
              cursorX: local.x,
              cursorY: local.y,
              moved: prev.moved || dx + dy > DRAG_THRESHOLD_PX,
            }
          : null,
      );
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
  }, [drag]);

  const onPortPointerDown = (
    parentId: string,
    branch: "match" | "miss",
    originX: number,
    originY: number,
    evt: ReactPointerEvent<SVGGElement>,
  ): void => {
    const local = clientToSvg(evt);
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

  // Per-node pointer handlers for highlight + drop.
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

  // Precompute a Set of node ids that are valid drop targets so the
  // visual can dim ineligible ones (e.g. the source parent itself).
  const validDropTargets = useMemo(() => {
    if (!drag) return null;
    const set = new Set<string>();
    for (const n of layout.nodes) {
      if (n.id !== drag.parentId) set.add(n.id);
    }
    return set;
  }, [drag, layout.nodes]);

  if (layout.nodes.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ap-line p-8 text-center text-sm text-ap-muted">
        {t("viewer.emptyTree")}
      </p>
    );
  }

  const canShowPorts = onAddChild !== undefined || onRewire !== undefined;

  return (
    <div className="overflow-auto rounded-xl border border-ap-line bg-ap-panel">
      <svg
        ref={svgRef}
        role="img"
        aria-label={t("viewer.svgAria")}
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="block touch-none"
        onClick={onSelectNode ? () => onSelectNode(null) : undefined}
      >
        {layout.edges.map((edge) => {
          const key = `${edge.from}->${edge.to}-${edge.branch}`;
          return (
            <EdgePath
              key={key}
              edge={edge}
              t={t}
              onPath={pathEdgeKeys?.has(key) ?? false}
            />
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
            onClick={onSelectNode}
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
            a click doesn't briefly flash a line. */}
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
      </svg>
    </div>
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
  onClick?: (nodeId: string | null) => void;
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
  onClick,
  onPointerEnter,
  onPointerLeave,
  onPointerUp,
}: NodeRectProps): JSX.Element {
  const { x, y, role, data } = node;
  const palette = paletteFor(role);
  const isInteractive = onClick !== undefined;
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
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      onPointerUp={onPointerUp}
      style={{ cursor: isInteractive ? "pointer" : "default", opacity }}
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
  onPointerDown: (
    originX: number,
    originY: number,
    evt: ReactPointerEvent<SVGGElement>,
  ) => void;
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
  const summary = data.label_en ?? "(unlabelled decision)";
  return (
    <>
      <text
        x={x + 12}
        y={y + 42}
        fontSize={13}
        fontWeight={600}
        fill="#0f172a"
      >
        Decision
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
  const outcome = data.outcome ?? {};
  const actionType = outcome.action_type ?? "—";
  const text = outcome.text_en ?? data.label_en ?? "";
  void role;
  return (
    <>
      <text
        x={x + 12}
        y={y + 42}
        fontSize={13}
        fontWeight={600}
        fill="#0f172a"
      >
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

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}
