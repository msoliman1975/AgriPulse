// Convert a dry-run path into highlight sets the canvas can render.
//
// The backend's dry-run returns an ordered list of `TreePathStepDTO`
// values: each step knows its node id and whether that node's
// condition matched (true / false / null=leaf). The edge to the next
// step follows the `match` branch when `matched=true`, the `miss`
// branch when `matched=false`, and doesn't exist on leaf rows.
//
// Pure fn for testability — the host wires the sets into TreeCanvas.

import type { TreePathStepDTO } from "@/api/decisionTrees";

export interface PathHighlight {
  /** Node ids visited on this path, in order. */
  nodes: Set<string>;
  /** Edge keys ("from->to-branch") traversed, in order. */
  edges: Set<string>;
  /** The last node id — typically the leaf. Surfaced separately so
   *  the host can give it extra visual weight (final outcome). */
  terminalNodeId: string | null;
}

export function pathHighlight(path: readonly TreePathStepDTO[]): PathHighlight {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  let terminal: string | null = null;
  for (let i = 0; i < path.length; i++) {
    const step = path[i];
    nodes.add(step.node_id);
    terminal = step.node_id;
    if (i < path.length - 1) {
      const next = path[i + 1];
      // matched=true → match branch; matched=false → miss branch.
      // matched=null is a leaf, which can't have an outgoing edge.
      if (step.matched === true) {
        edges.add(edgeKey(step.node_id, next.node_id, "match"));
      } else if (step.matched === false) {
        edges.add(edgeKey(step.node_id, next.node_id, "miss"));
      }
    }
  }
  return { nodes, edges, terminalNodeId: terminal };
}

/** Same key format as the edge map TreeCanvas builds for rendering. */
export function edgeKey(from: string, to: string, branch: "match" | "miss"): string {
  return `${from}->${to}-${branch}`;
}
