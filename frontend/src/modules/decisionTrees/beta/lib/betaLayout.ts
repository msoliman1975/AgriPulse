/**
 * Layered layout for a beta tree.
 *
 * `layout/treeLayout.ts` walks a strict binary tree and re-places a shared
 * child once per parent. A beta tree is a graph, not a tree: a switch has
 * n cases plus a default, register and set have one continuation, and almost
 * every route ends at the same `stop`. Drawing that shared node twice would
 * put two boxes with one id on the canvas.
 *
 * So each node is placed once. Depth is the longest route from the root, which
 * keeps every edge pointing downwards; within a depth, nodes keep the order the
 * walk first met them, so the picture does not jump when an unrelated node is
 * edited. A cycle cannot extend a depth, so a malformed body lays out instead
 * of hanging.
 */

import {
  betaNodeKind,
  edgeKey,
  outgoingEdges,
  type BetaNode,
  type BetaNodeKind,
  type BetaTreeDoc,
} from "./betaTree";

export const BETA_LAYOUT = {
  NODE_WIDTH: 248,
  NODE_HEIGHT: 108,
  /** A switch grows with its cases; each row adds this much. */
  SWITCH_ROW_HEIGHT: 16,
  COL_GAP: 40,
  ROW_GAP: 56,
  MARGIN: 32,
} as const;

export interface BetaPositionedNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  kind: BetaNodeKind;
  depth: number;
  data: BetaNode;
}

export interface BetaPositionedEdge {
  key: string;
  from: string;
  to: string;
  kind: "match" | "miss" | "next" | "case" | "default";
  caseIndex?: number;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

export interface BetaLayoutResult {
  nodes: BetaPositionedNode[];
  edges: BetaPositionedEdge[];
  byId: Map<string, BetaPositionedNode>;
  width: number;
  height: number;
}

const EMPTY: BetaLayoutResult = {
  nodes: [],
  edges: [],
  byId: new Map(),
  width: 0,
  height: 0,
};

/** How tall one node's box is. A switch shows its ordered cases and its
 *  default in the body, so it is as tall as it has rows. */
export function betaNodeHeight(node: BetaNode): number {
  if (betaNodeKind(node) !== "switch") return BETA_LAYOUT.NODE_HEIGHT;
  const rows = (node.switch?.cases?.length ?? 0) + 1; // + the default row
  return BETA_LAYOUT.NODE_HEIGHT + Math.max(0, rows - 2) * BETA_LAYOUT.SWITCH_ROW_HEIGHT;
}

export function layoutBetaTree(doc: BetaTreeDoc | null | undefined): BetaLayoutResult {
  if (!doc) return EMPTY;
  const nodes = doc.nodes ?? {};
  const rootId = doc.root;
  if (!rootId || !(rootId in nodes)) return EMPTY;

  // Depth = longest route from the root. Relax repeatedly, bounded by the
  // node count, so a cycle stops instead of deepening for ever.
  const depth = new Map<string, number>([[rootId, 0]]);
  const order: string[] = [rootId];
  const limit = Object.keys(nodes).length + 1;
  for (let pass = 0; pass < limit; pass++) {
    let changed = false;
    for (const id of [...order]) {
      const node = nodes[id];
      if (!node) continue;
      const here = depth.get(id) ?? 0;
      for (const edge of outgoingEdges(node)) {
        if (!nodes[edge.to]) continue;
        const known = depth.get(edge.to);
        if (known === undefined) {
          depth.set(edge.to, here + 1);
          order.push(edge.to);
          changed = true;
        } else if (known < here + 1) {
          depth.set(edge.to, here + 1);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }

  // Group by depth, keeping first-seen order inside each band.
  const bands = new Map<number, string[]>();
  for (const id of order) {
    const d = depth.get(id) ?? 0;
    const band = bands.get(d) ?? [];
    if (!band.includes(id)) band.push(id);
    bands.set(d, band);
  }

  // Row heights: a band is as tall as its tallest box.
  const depths = [...bands.keys()].sort((a, b) => a - b);
  const bandTop = new Map<number, number>();
  let cursorY = BETA_LAYOUT.MARGIN;
  for (const d of depths) {
    bandTop.set(d, cursorY);
    const tallest = Math.max(
      ...(bands.get(d) ?? []).map((id) => betaNodeHeight(nodes[id])),
      BETA_LAYOUT.NODE_HEIGHT,
    );
    cursorY += tallest + BETA_LAYOUT.ROW_GAP;
  }

  const placed = new Map<string, BetaPositionedNode>();
  for (const d of depths) {
    const band = bands.get(d) ?? [];
    band.forEach((id, index) => {
      const node = nodes[id];
      placed.set(id, {
        id,
        x: BETA_LAYOUT.MARGIN + index * (BETA_LAYOUT.NODE_WIDTH + BETA_LAYOUT.COL_GAP),
        y: bandTop.get(d)!,
        width: BETA_LAYOUT.NODE_WIDTH,
        height: betaNodeHeight(node),
        kind: betaNodeKind(node),
        depth: d,
        data: node,
      });
    });
  }

  // Centre each band over the widest one, so the graph reads as one column
  // rather than a left-aligned ladder.
  const widest = Math.max(...depths.map((d) => (bands.get(d) ?? []).length), 1);
  const fullWidth =
    BETA_LAYOUT.MARGIN * 2 + widest * BETA_LAYOUT.NODE_WIDTH + (widest - 1) * BETA_LAYOUT.COL_GAP;
  for (const d of depths) {
    const band = bands.get(d) ?? [];
    const bandWidth =
      band.length * BETA_LAYOUT.NODE_WIDTH + (band.length - 1) * BETA_LAYOUT.COL_GAP;
    const shift = (fullWidth - bandWidth) / 2 - BETA_LAYOUT.MARGIN;
    for (const id of band) {
      const p = placed.get(id)!;
      p.x += shift;
    }
  }

  const edges: BetaPositionedEdge[] = [];
  for (const [id, pos] of placed) {
    const outs = outgoingEdges(pos.data);
    outs.forEach((edge, index) => {
      const child = placed.get(edge.to);
      if (!child) return;
      // Fan the departure points across the bottom of the box so two edges
      // from one node do not leave the same pixel.
      const spread = (index + 1) / (outs.length + 1);
      const slot: Parameters<typeof edgeKey>[1] =
        edge.kind === "case" ? { kind: "case", index: edge.caseIndex ?? 0 } : { kind: edge.kind };
      edges.push({
        key: edgeKey(id, slot),
        from: id,
        to: edge.to,
        kind: edge.kind,
        caseIndex: edge.caseIndex,
        fromX: pos.x + pos.width * spread,
        fromY: pos.y + pos.height,
        toX: child.x + child.width / 2,
        toY: child.y,
      });
    });
  }

  let maxX = 0;
  let maxY = 0;
  for (const p of placed.values()) {
    maxX = Math.max(maxX, p.x + p.width);
    maxY = Math.max(maxY, p.y + p.height);
  }

  return {
    nodes: [...placed.values()],
    edges,
    byId: placed,
    width: maxX + BETA_LAYOUT.MARGIN,
    height: maxY + BETA_LAYOUT.MARGIN,
  };
}
