// Manual (hand-dragged) node positions for the tree canvas.
//
// `treeLayout.layoutTree` produces a deterministic auto-layout. An
// author working on a 30-40 node tree usually wants to move a few
// boxes so the branches read in order. This module holds that
// override layer:
//
//   * `applyManualPositions` takes the auto-layout and replaces the
//     (x, y) of any node the author has moved. Nodes with no manual
//     position keep the auto one, so a node added after a drag lands
//     at a sensible place instead of at the origin.
//   * Edge endpoints and the canvas bounding box are recomputed from
//     the final positions, so a dragged node keeps its wires.
//   * Positions live in the browser (localStorage), keyed by tree id.
//     They are NOT part of the tree body, so moving a box never marks
//     the draft dirty and never ships in a published version.
//
// Stale ids (a node deleted since the drag) are ignored on read and
// dropped on write, so the record can't grow without bound.

import type { LayoutResult, PositionedEdge } from "./treeLayout";
import { LAYOUT_CONSTANTS } from "./treeLayout";

const { NODE_WIDTH, NODE_HEIGHT, MARGIN } = LAYOUT_CONSTANTS;

export interface NodePosition {
  x: number;
  y: number;
}

export type PositionMap = Record<string, NodePosition>;

/** Persisted per-tree canvas preferences. `height` is the canvas
 *  viewport height in px (the author can drag the canvas taller). */
export interface CanvasPrefs {
  positions: PositionMap;
  height: number;
}

export const DEFAULT_CANVAS_HEIGHT = 560;
export const MIN_CANVAS_HEIGHT = 240;
export const MAX_CANVAS_HEIGHT = 2000;

export function clampCanvasHeight(h: number): number {
  if (!Number.isFinite(h)) return DEFAULT_CANVAS_HEIGHT;
  return Math.min(MAX_CANVAS_HEIGHT, Math.max(MIN_CANVAS_HEIGHT, Math.round(h)));
}

/** Overlay manual positions onto an auto-layout. Returns a new
 *  LayoutResult; the input is not mutated. Manual entries for ids the
 *  layout doesn't contain are ignored. */
export function applyManualPositions(layout: LayoutResult, positions: PositionMap): LayoutResult {
  if (layout.nodes.length === 0) return layout;
  const ids = new Set(layout.nodes.map((n) => n.id));
  let touched = false;
  for (const id of Object.keys(positions)) {
    if (ids.has(id)) {
      touched = true;
      break;
    }
  }
  if (!touched) return layout;

  const nodes = layout.nodes.map((n) => {
    const manual = positions[n.id];
    if (!manual || !Number.isFinite(manual.x) || !Number.isFinite(manual.y)) return n;
    return { ...n, x: manual.x, y: manual.y };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: PositionedEdge[] = [];
  for (const edge of layout.edges) {
    const from = byId.get(edge.from);
    const to = byId.get(edge.to);
    if (!from || !to) continue;
    edges.push({
      ...edge,
      fromX: from.x + NODE_WIDTH / 2,
      fromY: from.y + NODE_HEIGHT,
      toX: to.x + NODE_WIDTH / 2,
      toY: to.y,
    });
  }

  let maxX = 0;
  let maxY = 0;
  for (const n of nodes) {
    maxX = Math.max(maxX, n.x + NODE_WIDTH);
    // The branch ports hang ~29px below the box; keep them inside the
    // bounding box so a node dragged to the bottom isn't clipped on
    // export.
    maxY = Math.max(maxY, n.y + NODE_HEIGHT + 32);
  }

  return { nodes, edges, width: maxX + MARGIN, height: maxY + MARGIN };
}

// ---- Persistence ---------------------------------------------------

const STORAGE_PREFIX = "ap.dt.canvas.v1.";

function storageKey(treeId: string): string {
  return `${STORAGE_PREFIX}${treeId}`;
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private mode / blocked site data — treat as "no saved layout".
    return null;
  }
}

/** Read saved prefs for a tree. Returns defaults when nothing is
 *  stored or the record is unreadable. Never throws. */
export function loadCanvasPrefs(treeId: string): CanvasPrefs {
  const empty: CanvasPrefs = { positions: {}, height: DEFAULT_CANVAS_HEIGHT };
  if (!treeId) return empty;
  const raw = readStorage(storageKey(treeId));
  if (!raw) return empty;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return empty;
  }
  return normalizePrefs(parsed);
}

/** Coerce an unknown parsed record into CanvasPrefs, dropping any
 *  entry that isn't a finite (x, y) pair. Exported for tests. */
export function normalizePrefs(parsed: unknown): CanvasPrefs {
  const empty: CanvasPrefs = { positions: {}, height: DEFAULT_CANVAS_HEIGHT };
  if (!parsed || typeof parsed !== "object") return empty;
  const record = parsed as { positions?: unknown; height?: unknown };
  const positions: PositionMap = {};
  if (record.positions && typeof record.positions === "object") {
    for (const [id, value] of Object.entries(record.positions as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const { x, y } = value as { x?: unknown; y?: unknown };
      if (typeof x !== "number" || typeof y !== "number") continue;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      positions[id] = { x, y };
    }
  }
  const height =
    typeof record.height === "number" ? clampCanvasHeight(record.height) : DEFAULT_CANVAS_HEIGHT;
  return { positions, height };
}

/** Write prefs for a tree. `knownNodeIds`, when given, prunes
 *  positions for nodes that no longer exist. Never throws. */
export function saveCanvasPrefs(
  treeId: string,
  prefs: CanvasPrefs,
  knownNodeIds?: Iterable<string>,
): void {
  if (!treeId) return;
  const positions = knownNodeIds ? prunePositions(prefs.positions, knownNodeIds) : prefs.positions;
  const payload = JSON.stringify({ positions, height: clampCanvasHeight(prefs.height) });
  try {
    window.localStorage.setItem(storageKey(treeId), payload);
  } catch {
    // Quota or blocked storage — the layout just won't survive a reload.
  }
}

export function prunePositions(
  positions: PositionMap,
  knownNodeIds: Iterable<string>,
): PositionMap {
  const known = new Set(knownNodeIds);
  const next: PositionMap = {};
  for (const [id, pos] of Object.entries(positions)) {
    if (known.has(id)) next[id] = pos;
  }
  return next;
}
