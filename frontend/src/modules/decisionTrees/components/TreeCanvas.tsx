// Read-only SVG renderer for a compiled decision tree (PR-D1).
//
// Takes a LayoutResult from `treeLayout.ts` and draws each node as a
// rounded rect with role-colored chrome. Decision nodes show the
// condition summary text; leaf nodes show kind chip + action_type +
// the (truncated) leaf text. Edges are drawn as orthogonal Bezier
// curves from parent bottom to child top, color-coded by branch
// (green for `match`, slate for `miss`).
//
// Pure presentational — accepts no state. PR-D2 will introduce
// click-to-select / hover overlays; D1 stays read-only.

import { useTranslation } from "react-i18next";

import type { LayoutResult, PositionedNode } from "../layout/treeLayout";
import { LAYOUT_CONSTANTS } from "../layout/treeLayout";

const { NODE_WIDTH, NODE_HEIGHT } = LAYOUT_CONSTANTS;

interface TreeCanvasProps {
  layout: LayoutResult;
}

export function TreeCanvas({ layout }: TreeCanvasProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");

  if (layout.nodes.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ap-line p-8 text-center text-sm text-ap-muted">
        {t("viewer.emptyTree")}
      </p>
    );
  }

  return (
    <div className="overflow-auto rounded-xl border border-ap-line bg-ap-panel">
      <svg
        role="img"
        aria-label={t("viewer.svgAria")}
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="block"
      >
        {/* Edges drawn first so nodes sit on top. */}
        {layout.edges.map((edge) => (
          <EdgePath key={`${edge.from}->${edge.to}-${edge.branch}`} edge={edge} t={t} />
        ))}
        {layout.nodes.map((node) => (
          <NodeRect key={node.id} node={node} />
        ))}
      </svg>
    </div>
  );
}

// ---- Edge ----------------------------------------------------------

interface EdgePathProps {
  edge: LayoutResult["edges"][number];
  t: ReturnType<typeof useTranslation>["t"];
}

function EdgePath({ edge, t }: EdgePathProps): JSX.Element {
  // Smooth S-curve between (fromX, fromY) and (toX, toY) via a cubic
  // Bezier with vertical control handles. Match edges go solid green;
  // miss edges go dashed slate so the user reads branch direction
  // without needing to hit the label.
  const dx = edge.toX - edge.fromX;
  const dy = edge.toY - edge.fromY;
  const c1x = edge.fromX;
  const c1y = edge.fromY + dy * 0.5;
  const c2x = edge.toX;
  const c2y = edge.toY - dy * 0.5;
  const d = `M ${edge.fromX} ${edge.fromY} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${edge.toX} ${edge.toY}`;

  const isMatch = edge.branch === "match";
  const stroke = isMatch ? "#16a34a" : "#94a3b8"; // green-600 / slate-400
  const label = isMatch ? t("viewer.edges.match") : t("viewer.edges.miss");

  // Label sits at the midpoint of the curve. Anchored against the dx
  // sign so left-going edges put their label to the right of the
  // curve and vice-versa — keeps text from running across nearby
  // nodes on dense layouts.
  const midX = (edge.fromX + edge.toX) / 2 + (dx >= 0 ? 8 : -8);
  const midY = (edge.fromY + edge.toY) / 2;

  return (
    <g>
      <path
        d={d}
        stroke={stroke}
        strokeWidth={2}
        strokeDasharray={isMatch ? undefined : "5 4"}
        fill="none"
        opacity={0.85}
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
}

function NodeRect({ node }: NodeRectProps): JSX.Element {
  const { x, y, role, data } = node;
  const palette = paletteFor(role);

  return (
    <g>
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
      {/* Node id strip — small monospace badge in top-left so the
          editor reading the YAML can cross-reference. */}
      <text
        x={x + 12}
        y={y + 16}
        fontSize={10}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={palette.dim}
      >
        {node.id}
      </text>
      {/* Role chip — top-right, color-coded. */}
      <RoleChip x={x + NODE_WIDTH - 90} y={y + 8} role={role} data={data} />
      {/* Main content line. */}
      {role === "decision" ? (
        <DecisionBody x={x} y={y} data={data} />
      ) : (
        <LeafBody x={x} y={y} role={role} data={data} />
      )}
    </g>
  );
}

function DecisionBody({
  x,
  y,
  data,
}: {
  x: number;
  y: number;
  data: PositionedNode["data"];
}): JSX.Element {
  // For V1 the condition summary is "decision" plus the optional
  // human label_en. The full condition tree is in the YAML editor;
  // PR-D2 will surface a richer inline preview.
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
    text = c !== undefined ? `${t("viewer.chips.recommendation")} · ${c}` : t("viewer.chips.recommendation");
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
      // amber-tinted to read as "watch / action needed"
      return {
        bg: "#fffbeb",
        border: "#f59e0b",
        dim: "#92400e",
        chipBg: "#fde68a",
        chipBorder: "#f59e0b",
        chipText: "#7c2d12",
      };
    case "leaf-recommendation":
      // emerald-tinted to read as "do this"
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
