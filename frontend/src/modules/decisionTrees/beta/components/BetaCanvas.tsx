/**
 * The beta canvas: five node kinds on one surface.
 *
 * Interaction is copied from `components/TreeCanvas.tsx` — background drag to
 * pan, Ctrl/Cmd and wheel to zoom about the cursor, click to select, a `+`
 * port on every empty pointer, a resize grip at the bottom, and the whole
 * surface wrapped in `<Card>`. The viewport maths is the shared
 * `lib/canvasViewport.ts`, not a second copy.
 *
 * What is different is the graph. A beta tree is not binary: a switch has n
 * cases plus a default, register and set have one continuation, and almost
 * every route ends at the same `stop`. So the layout places each node once
 * (`lib/betaLayout.ts`) and this file draws n outgoing edges per node.
 *
 * A switch node draws its ordered cases and its default inside the box, so an
 * author reads the bands without opening the node.
 *
 * `dir="ltr"` on the viewport is load-bearing: text anchored in SVG flips
 * under RTL, and a node id or a band bound would read backwards in Arabic.
 * The surrounding page stays RTL.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { localizedField } from "@/lib/localizedField";

import {
  IDENTITY_VIEWPORT,
  ZOOM_STEP,
  fitToViewport,
  zoomAt,
  zoomAtCentre,
  zoomPercent,
  type Viewport,
} from "../../lib/canvasViewport";
import {
  BETA_LAYOUT,
  type BetaLayoutResult,
  type BetaPositionedEdge,
  type BetaPositionedNode,
} from "../lib/betaLayout";
import { slotsOf, type BetaNode, type BetaNodeKind, type EdgeSlot } from "../lib/betaTree";
import { describeOperand, describeValueRef } from "../lib/betaValueRef";

const DRAG_THRESHOLD_PX = 4;

interface BetaCanvasProps {
  layout: BetaLayoutResult;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  /** Click a `+` port: add a node into that empty slot. */
  onAddNode?: (parentId: string, slot: EdgeSlot) => void;
  /** Nodes a publish rejection names. Drawn with a red halo. */
  rejectedNodeIds?: ReadonlySet<string>;
  /** Edges a publish rejection names, by `edgeKey`. */
  rejectedEdgeKeys?: ReadonlySet<string>;
  /** Cells the dry run walked through, for the path overlay. */
  pathNodeIds?: ReadonlySet<string>;
  height: number;
  onHeightChange: (height: number) => void;
}

interface PanState {
  startScreenX: number;
  startScreenY: number;
  originTx: number;
  originTy: number;
  moved: boolean;
}

export function BetaCanvas({
  layout,
  selectedNodeId,
  onSelectNode,
  onAddNode,
  rejectedNodeIds,
  rejectedEdgeKeys,
  pathNodeIds,
  height,
  onHeightChange,
}: BetaCanvasProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<Viewport>(IDENTITY_VIEWPORT);
  const [pan, setPan] = useState<PanState | null>(null);
  const suppressBackgroundClick = useRef(false);

  const viewportSize = useCallback((): { width: number; height: number } => {
    const el = containerRef.current;
    if (!el) return { width: 0, height: 0 };
    const rect = el.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }, []);

  const fitToScreen = useCallback(() => {
    const size = viewportSize();
    if (size.width === 0 || size.height === 0) return;
    setView(fitToViewport({ width: layout.width, height: layout.height }, size));
  }, [layout.width, layout.height, viewportSize]);

  // Fit once, when there is first something to fit. After that the view is
  // the author's; re-fitting on every edit would pull it out from under them.
  const didFit = useRef(false);
  useEffect(() => {
    if (didFit.current || layout.nodes.length === 0) return;
    const size = viewportSize();
    if (size.width === 0 || size.height === 0) return;
    didFit.current = true;
    fitToScreen();
  }, [layout.nodes.length, fitToScreen, viewportSize]);

  // Ctrl/Cmd + wheel zooms about the cursor; a plain wheel still scrolls the
  // page. Registered natively because the listener must be non-passive.
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

  useEffect(() => {
    if (!pan) return;
    const onMove = (evt: PointerEvent): void => {
      setPan((prev) => {
        if (!prev) return null;
        const dx = evt.clientX - prev.startScreenX;
        const dy = evt.clientY - prev.startScreenY;
        setView((v) => ({ ...v, tx: prev.originTx + dx, ty: prev.originTy + dy }));
        return {
          ...prev,
          moved: prev.moved || Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD_PX,
        };
      });
    };
    const onUp = (): void => {
      setPan((prev) => {
        if (prev?.moved) suppressBackgroundClick.current = true;
        return null;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [pan]);

  const onBackgroundPointerDown = (evt: ReactPointerEvent<SVGSVGElement>): void => {
    setPan({
      startScreenX: evt.clientX,
      startScreenY: evt.clientY,
      originTx: view.tx,
      originTy: view.ty,
      moved: false,
    });
  };

  const onBackgroundClick = (): void => {
    if (suppressBackgroundClick.current) {
      suppressBackgroundClick.current = false;
      return;
    }
    onSelectNode(null);
  };

  const [resizeStart, setResizeStart] = useState<{ y: number; height: number } | null>(null);
  useEffect(() => {
    if (!resizeStart) return;
    const onMove = (evt: PointerEvent): void => {
      onHeightChange(Math.max(240, resizeStart.height + (evt.clientY - resizeStart.y)));
    };
    const onUp = (): void => setResizeStart(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [resizeStart, onHeightChange]);

  const ports = useMemo(() => collectPorts(layout), [layout]);

  return (
    <Card noPadding className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-ap-line px-3 py-2">
        <Button variant="secondary" size="sm" onClick={fitToScreen}>
          {t("canvas.fitToScreen")}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          aria-label={t("canvas.zoomOut")}
          onClick={() => setView((v) => zoomAtCentre(v, 1 / ZOOM_STEP, viewportSize()))}
        >
          −
        </Button>
        <span dir="ltr" className="w-12 text-center text-meta tabular-nums text-ap-muted">
          {zoomPercent(view)}%
        </span>
        <Button
          variant="secondary"
          size="sm"
          aria-label={t("canvas.zoomIn")}
          onClick={() => setView((v) => zoomAtCentre(v, ZOOM_STEP, viewportSize()))}
        >
          +
        </Button>
        <span className="ms-auto text-meta text-ap-muted">
          {t("canvas.nodeCount", { count: layout.nodes.length })} · {t("canvas.hint")}
        </span>
      </div>
      <div
        ref={containerRef}
        dir="ltr"
        role="application"
        aria-label={t("canvas.aria")}
        className="relative overflow-hidden bg-ap-bg"
        style={{ height, touchAction: "none" }}
      >
        {layout.nodes.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("canvas.empty")}</p>
        ) : (
          <svg
            width="100%"
            height="100%"
            className="block select-none"
            style={{ cursor: pan?.moved ? "grabbing" : "grab" }}
            onPointerDown={onBackgroundPointerDown}
            onClick={onBackgroundClick}
          >
            <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
              {layout.edges.map((edge) => (
                <BetaEdge
                  key={edge.key}
                  edge={edge}
                  rejected={rejectedEdgeKeys?.has(edge.key) ?? false}
                />
              ))}
              {layout.nodes.map((node) => (
                <BetaNodeBox
                  key={node.id}
                  node={node}
                  selected={node.id === selectedNodeId}
                  rejected={rejectedNodeIds?.has(node.id) ?? false}
                  onPath={pathNodeIds?.has(node.id) ?? false}
                  onClick={onSelectNode}
                />
              ))}
              {onAddNode
                ? ports.map((port) => (
                    <AddPort
                      key={`${port.parentId}-${port.label}`}
                      x={port.x}
                      y={port.y}
                      title={port.title}
                      onClick={() => onAddNode(port.parentId, port.slot)}
                    />
                  ))
                : null}
            </g>
          </svg>
        )}
      </div>
      <button
        type="button"
        aria-label={t("canvas.resizeGrip")}
        onPointerDown={(evt) => setResizeStart({ y: evt.clientY, height })}
        className="flex h-3 w-full cursor-ns-resize items-center justify-center border-t border-ap-line bg-ap-panel hover:bg-ap-line/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ap-primary"
      >
        <span className="h-0.5 w-10 rounded-full bg-ap-line" aria-hidden="true" />
      </button>
    </Card>
  );
}

// ---- Ports ------------------------------------------------------------

interface Port {
  parentId: string;
  slot: EdgeSlot;
  label: string;
  title: string;
  x: number;
  y: number;
}

/** A `+` under every empty outgoing pointer. A `stop` has none, which is the
 *  visual difference between "the walk ends" and "the author forgot". */
function collectPorts(layout: BetaLayoutResult): Port[] {
  const ports: Port[] = [];
  for (const node of layout.nodes) {
    const slots = slotsOf(node.data);
    const empty = slots.filter((slot) => readTarget(node.data, slot) === null);
    empty.forEach((slot, index) => {
      const spread = (index + 1) / (empty.length + 1);
      const label = slot.kind === "case" ? `case-${slot.index}` : slot.kind;
      ports.push({
        parentId: node.id,
        slot,
        label,
        title: label,
        x: node.x + node.width * spread,
        y: node.y + node.height + 16,
      });
    });
  }
  return ports;
}

function readTarget(node: BetaNode, slot: EdgeSlot): string | null {
  switch (slot.kind) {
    case "match":
      return node.on_match ?? null;
    case "miss":
      return node.on_miss ?? null;
    case "next":
      return node.next ?? null;
    case "case":
      return node.switch?.cases?.[slot.index]?.go || null;
    case "default":
      return node.switch?.default || null;
  }
}

function AddPort({
  x,
  y,
  title,
  onClick,
}: {
  x: number;
  y: number;
  title: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <g
      style={{ cursor: "pointer" }}
      onClick={(evt) => {
        evt.stopPropagation();
        onClick();
      }}
      onPointerDown={(evt) => evt.stopPropagation()}
    >
      <title>{title}</title>
      <circle cx={x} cy={y} r={11} fill="#ffffff" stroke="#94a3b8" strokeWidth={1.5} />
      <line x1={x - 5} y1={y} x2={x + 5} y2={y} stroke="#475569" strokeWidth={1.75} />
      <line x1={x} y1={y - 5} x2={x} y2={y + 5} stroke="#475569" strokeWidth={1.75} />
    </g>
  );
}

// ---- Edge -------------------------------------------------------------

const EDGE_COLOR: Record<BetaPositionedEdge["kind"], string> = {
  match: "#16a34a",
  miss: "#94a3b8",
  next: "#6366f1",
  case: "#0891b2",
  default: "#a855f7",
};

function BetaEdge({
  edge,
  rejected,
}: {
  edge: BetaPositionedEdge;
  rejected: boolean;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const dy = edge.toY - edge.fromY;
  const d = `M ${edge.fromX} ${edge.fromY} C ${edge.fromX} ${edge.fromY + dy * 0.5}, ${edge.toX} ${edge.toY - dy * 0.5}, ${edge.toX} ${edge.toY}`;
  const stroke = rejected ? "#dc2626" : EDGE_COLOR[edge.kind];
  const label =
    edge.kind === "case"
      ? t("canvas.edge.case", { position: (edge.caseIndex ?? 0) + 1 })
      : t(`canvas.edge.${edge.kind}`);
  const dx = edge.toX - edge.fromX;
  return (
    <g>
      <path
        d={d}
        stroke={stroke}
        strokeWidth={rejected ? 3 : 2}
        strokeDasharray={edge.kind === "miss" || edge.kind === "default" ? "5 4" : undefined}
        fill="none"
        opacity={0.9}
      />
      <text
        x={(edge.fromX + edge.toX) / 2 + (dx >= 0 ? 6 : -6)}
        y={(edge.fromY + edge.toY) / 2}
        fontSize={11}
        fill={stroke}
        dominantBaseline="middle"
        textAnchor={dx >= 0 ? "start" : "end"}
      >
        {label}
      </text>
    </g>
  );
}

// ---- Node -------------------------------------------------------------

interface Palette {
  bg: string;
  border: string;
  dim: string;
  chipBg: string;
  chipText: string;
}

const PALETTE: Record<BetaNodeKind, Palette> = {
  condition: {
    bg: "#ffffff",
    border: "#94a3b8",
    dim: "#475569",
    chipBg: "#e0e7ff",
    chipText: "#3730a3",
  },
  register: {
    bg: "#fffbeb",
    border: "#f59e0b",
    dim: "#92400e",
    chipBg: "#fde68a",
    chipText: "#7c2d12",
  },
  set: {
    bg: "#eef2ff",
    border: "#6366f1",
    dim: "#3730a3",
    chipBg: "#c7d2fe",
    chipText: "#312e81",
  },
  switch: {
    bg: "#ecfeff",
    border: "#0891b2",
    dim: "#155e75",
    chipBg: "#a5f3fc",
    chipText: "#164e63",
  },
  stop: {
    bg: "#f8fafc",
    border: "#475569",
    dim: "#334155",
    chipBg: "#e2e8f0",
    chipText: "#1e293b",
  },
};

function BetaNodeBox({
  node,
  selected,
  rejected,
  onPath,
  onClick,
}: {
  node: BetaPositionedNode;
  selected: boolean;
  rejected: boolean;
  onPath: boolean;
  onClick: (id: string) => void;
}): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const palette = PALETTE[node.kind];
  const clipId = `beta-node-${node.id.replace(/[^A-Za-z0-9_-]/g, "_") || "node"}`;
  const label =
    localizedField(i18n.language, node.data.label_en ?? null, node.data.label_ar ?? null) ||
    t("canvas.body.unlabelled");

  return (
    <g
      // An SVG group carries no accessible name, so the node id and whether a
      // check named it are exposed as data attributes. That is what lets a
      // browser test assert an error landed on the right box rather than
      // only that a message with the id in it appeared somewhere.
      data-node-id={node.id}
      data-rejected={rejected ? "true" : "false"}
      style={{ cursor: "pointer" }}
      onClick={(evt) => {
        evt.stopPropagation();
        onClick(node.id);
      }}
      onPointerDown={(evt) => evt.stopPropagation()}
    >
      {selected ? (
        <rect
          x={node.x - 4}
          y={node.y - 4}
          width={node.width + 8}
          height={node.height + 8}
          rx={12}
          fill="none"
          stroke="#2563eb"
          strokeWidth={2.5}
          strokeDasharray="6 3"
        />
      ) : null}
      {rejected ? (
        <rect
          x={node.x - 3}
          y={node.y - 3}
          width={node.width + 6}
          height={node.height + 6}
          rx={12}
          fill="#fee2e2"
          stroke="#dc2626"
          strokeWidth={2.5}
        />
      ) : null}
      {onPath && !rejected ? (
        <rect
          x={node.x - 3}
          y={node.y - 3}
          width={node.width + 6}
          height={node.height + 6}
          rx={12}
          fill="#fde04822"
          stroke="#facc15"
          strokeWidth={2}
        />
      ) : null}
      <rect
        x={node.x}
        y={node.y}
        width={node.width}
        height={node.height}
        rx={10}
        fill={palette.bg}
        stroke={palette.border}
        strokeWidth={1.5}
      />
      <clipPath id={clipId}>
        <rect x={node.x} y={node.y} width={node.width} height={node.height} rx={10} />
      </clipPath>
      <g clipPath={`url(#${clipId})`}>
        <text
          x={node.x + 12}
          y={node.y + 17}
          fontSize={10}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fill={palette.dim}
        >
          {node.id}
        </text>
        <rect
          x={node.x + node.width - 84}
          y={node.y + 8}
          width={72}
          height={18}
          rx={9}
          fill={palette.chipBg}
        />
        <text
          x={node.x + node.width - 48}
          y={node.y + 21}
          fontSize={10}
          fontWeight={600}
          fill={palette.chipText}
          textAnchor="middle"
        >
          {t(`canvas.kind.${node.kind}`)}
        </text>
        <text x={node.x + 12} y={node.y + 42} fontSize={13} fontWeight={600} fill="#0f172a">
          {truncate(label, 28)}
        </text>
        <NodeBody node={node} />
      </g>
    </g>
  );
}

function NodeBody({ node }: { node: BetaPositionedNode }): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const x = node.x + 12;
  const data = node.data;

  if (node.kind === "register") {
    const code = data.register?.code;
    const severity = data.register?.severity ?? "warning";
    return (
      <>
        <text x={x} y={node.y + 64} fontSize={12} fill="#475569">
          {code ? t("canvas.body.registers", { code }) : t("canvas.body.noCode")}
        </text>
        <text x={x} y={node.y + 84} fontSize={11} fontWeight={600} fill={SEVERITY_INK[severity]}>
          {t(`severity.${severity}`)}
        </text>
      </>
    );
  }

  if (node.kind === "set") {
    const names = Object.keys(data.set ?? {});
    return (
      <>
        <text x={x} y={node.y + 64} fontSize={12} fill="#475569">
          {names.length === 0
            ? t("canvas.body.setsNone")
            : t("canvas.body.setsCount", { count: names.length })}
        </text>
        <text
          x={x}
          y={node.y + 84}
          fontSize={11}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fill="#64748b"
        >
          {truncate(names.join(", "), 32)}
        </text>
      </>
    );
  }

  if (node.kind === "switch") {
    // The whole point of the taller box: the ordered bands and the default
    // are readable without opening the node.
    const cases = data.switch?.cases ?? [];
    const subject = describeValueRef(data.switch?.on);
    const rows = cases.map((c, i) => (
      <text
        key={i}
        x={x}
        y={node.y + 80 + i * BETA_LAYOUT.SWITCH_ROW_HEIGHT}
        fontSize={11}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill="#155e75"
      >
        {truncate(`${i + 1}. ${t(`op.${c.op}`)} ${describeOperand(c.value)} → ${c.go || "—"}`, 34)}
      </text>
    ));
    const defaultTarget = data.switch?.default;
    return (
      <>
        <text x={x} y={node.y + 62} fontSize={11} fill="#475569">
          {truncate(t("canvas.body.switchOn", { subject }), 34)}
        </text>
        {rows}
        <text
          x={x}
          y={node.y + 80 + cases.length * BETA_LAYOUT.SWITCH_ROW_HEIGHT}
          fontSize={11}
          fontWeight={600}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fill={defaultTarget ? "#7e22ce" : "#dc2626"}
        >
          {defaultTarget
            ? truncate(t("canvas.body.switchDefault", { target: defaultTarget }), 34)
            : t("canvas.body.switchNoDefault")}
        </text>
      </>
    );
  }

  if (node.kind === "stop") {
    return (
      <text x={x} y={node.y + 64} fontSize={12} fill="#475569">
        {t("canvas.body.stop")}
      </text>
    );
  }

  return (
    <text x={x} y={node.y + 64} fontSize={12} fill="#475569">
      {truncate(describeCondition(node.data), 34)}
    </text>
  );
}

const SEVERITY_INK: Record<string, string> = {
  info: "#0369a1",
  warning: "#b45309",
  critical: "#b91c1c",
};

function describeCondition(node: BetaNode): string {
  const tree = node.condition?.tree;
  if (!tree || typeof tree !== "object") return "—";
  const c = tree as Record<string, unknown>;
  if (typeof c.op === "string" && c.left) {
    return `${describeValueRef(c.left)} ${c.op} ${describeOperand(c.right)}`;
  }
  if (Array.isArray(c.all)) return `all of ${c.all.length}`;
  if (Array.isArray(c.any)) return `any of ${c.any.length}`;
  return "—";
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}
