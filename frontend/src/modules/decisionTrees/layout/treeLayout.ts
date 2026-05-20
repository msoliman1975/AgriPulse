// Top-down layout for a compiled decision tree (PR-D1).
//
// Walks the tree from the root and assigns each node an (x, y) on a
// grid. Y = depth from root. X for each node is centred over the
// midpoint of its subtree's leaf positions, so balanced trees come
// out symmetric and unbalanced ones spread proportional to their
// subtree size. Cycles are guarded by a visited set — a malformed
// compiled body that loops back would otherwise blow the stack.
//
// Public shape (PositionedNode / PositionedEdge) is deliberately
// pre-rendered: TreeCanvas consumes the result without re-walking the
// compiled JSON. Px sizes come from constants here so tweaking visual
// density in PR-D2 is one place to edit.
//
// Limitations (acceptable for V1):
//   * Subtrees rooted at the same depth that point at the same shared
//     child render that child twice (once per parent path). True DAGs
//     would need a separate pass to merge nodes; trees in our YAML
//     don't have shared sub-paths today.
//   * No edge bundling / no crossing minimization. Small trees stay
//     readable; if we ever ship 50-node trees we revisit.

export interface CompiledNode {
  condition?: { tree?: unknown };
  on_match?: string;
  on_miss?: string;
  outcome?: {
    action_type?: string;
    kind?: string; // "alert" | "recommendation" (PR-E); default "recommendation"
    severity?: string;
    confidence?: number | string;
    text_en?: string;
    text_ar?: string | null;
    parameters?: Record<string, unknown>;
  };
  label_en?: string;
  label_ar?: string | null;
}

export interface CompiledTree {
  root?: string;
  nodes?: Record<string, CompiledNode>;
  // Mirrors backend `compile_tree` output. PR-B; PR-D3 reads this on
  // the viewer page to surface the parameters editor.
  parameters?: Record<string, unknown>;
}

export type NodeRole = "decision" | "leaf-recommendation" | "leaf-alert" | "leaf-noop";

export interface PositionedNode {
  id: string;
  x: number;
  y: number;
  role: NodeRole;
  data: CompiledNode;
}

export interface PositionedEdge {
  from: string;
  to: string;
  branch: "match" | "miss";
  // Pre-computed segment endpoints so TreeCanvas doesn't re-look-up
  // the positioned node by id at render time.
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

export interface LayoutResult {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
}

// ---- Visual constants (kept here so PR-D2 has one place to tweak) ---

const NODE_WIDTH = 240;
const NODE_HEIGHT = 88;
const COL_GAP = 32;
const ROW_GAP = 56;
const MARGIN = 32;

// ---- Layout pipeline -----------------------------------------------

/** Walk the compiled tree and produce nodes + edges at concrete pixel
 *  coordinates. Returns an empty result when the compiled body is
 *  malformed (missing root / nodes); the caller renders an empty
 *  placeholder instead of crashing. */
export function layoutTree(compiled: CompiledTree | undefined | null): LayoutResult {
  if (!compiled || typeof compiled !== "object") {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }
  const nodes = compiled.nodes ?? {};
  const rootId = compiled.root;
  if (!rootId || !(rootId in nodes)) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  // Step 1: assign each node a leaf-count so we can size its
  // horizontal slot proportional to its subtree size.
  const leafCounts = new Map<string, number>();
  const visited = new Set<string>();
  const computeLeafCount = (id: string): number => {
    if (visited.has(id)) {
      // Cycle → treat as a leaf for layout purposes.
      return 1;
    }
    visited.add(id);
    const cached = leafCounts.get(id);
    if (cached !== undefined) {
      visited.delete(id);
      return cached;
    }
    const node = nodes[id];
    let count = 1;
    if (node && !node.outcome) {
      const matchN = node.on_match && nodes[node.on_match] ? computeLeafCount(node.on_match) : 0;
      const missN = node.on_miss && nodes[node.on_miss] ? computeLeafCount(node.on_miss) : 0;
      count = Math.max(1, matchN + missN);
    }
    leafCounts.set(id, count);
    visited.delete(id);
    return count;
  };
  computeLeafCount(rootId);

  // Step 2: place each node. Each subtree gets an x-range proportional
  // to its leaf-count; the node sits at the midpoint of its range.
  const positioned = new Map<string, PositionedNode>();
  const place = (id: string, depth: number, xStart: number): number => {
    if (positioned.has(id)) {
      // Defensive: shouldn't happen in a tree, but bail to avoid double-place.
      return positioned.get(id)!.x;
    }
    const node = nodes[id];
    if (!node) return xStart;

    const leafN = leafCounts.get(id) ?? 1;
    const xEnd = xStart + leafN * (NODE_WIDTH + COL_GAP) - COL_GAP;
    const xCenter = (xStart + xEnd) / 2;

    let role: NodeRole = "decision";
    if (node.outcome) {
      const kind = (node.outcome.kind ?? "recommendation").toString();
      if (node.outcome.action_type === "no_action") {
        role = "leaf-noop";
      } else if (kind === "alert") {
        role = "leaf-alert";
      } else {
        role = "leaf-recommendation";
      }
    }

    positioned.set(id, {
      id,
      x: xCenter,
      y: depth * (NODE_HEIGHT + ROW_GAP) + MARGIN,
      role,
      data: node,
    });

    if (!node.outcome) {
      // Place children left-to-right: match goes first, miss second.
      let cursor = xStart;
      if (node.on_match && nodes[node.on_match]) {
        const childN = leafCounts.get(node.on_match) ?? 1;
        place(node.on_match, depth + 1, cursor);
        cursor += childN * (NODE_WIDTH + COL_GAP);
      }
      if (node.on_miss && nodes[node.on_miss]) {
        place(node.on_miss, depth + 1, cursor);
      }
    }

    return xCenter;
  };
  place(rootId, 0, MARGIN);

  // Step 3: derive edges with pre-computed endpoints. Edge starts at
  // bottom-centre of parent, ends at top-centre of child.
  const edges: PositionedEdge[] = [];
  for (const [id, pos] of positioned) {
    const node = pos.data;
    if (node.outcome) continue;
    const fromX = pos.x + NODE_WIDTH / 2;
    const fromY = pos.y + NODE_HEIGHT;
    const pushEdge = (childId: string | undefined, branch: "match" | "miss"): void => {
      if (!childId) return;
      const child = positioned.get(childId);
      if (!child) return;
      edges.push({
        from: id,
        to: childId,
        branch,
        fromX,
        fromY,
        toX: child.x + NODE_WIDTH / 2,
        toY: child.y,
      });
    };
    pushEdge(node.on_match, "match");
    pushEdge(node.on_miss, "miss");
  }

  // Step 4: tight bounding box. We translated nothing so left edge is
  // at MARGIN by construction.
  let maxX = 0;
  let maxY = 0;
  for (const n of positioned.values()) {
    maxX = Math.max(maxX, n.x + NODE_WIDTH);
    maxY = Math.max(maxY, n.y + NODE_HEIGHT);
  }

  return {
    nodes: [...positioned.values()],
    edges,
    width: maxX + MARGIN,
    height: maxY + MARGIN,
  };
}

// Visual constants exported for the canvas component so the two
// stay in sync without prop-drilling.
export const LAYOUT_CONSTANTS = {
  NODE_WIDTH,
  NODE_HEIGHT,
  COL_GAP,
  ROW_GAP,
  MARGIN,
} as const;
