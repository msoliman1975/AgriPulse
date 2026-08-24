// Owns the per-tree canvas preferences: hand-dragged node positions
// and the canvas height. Both live in the browser only (see
// `layout/manualPositions.ts`), so nothing here touches the tree body
// or the dirty state.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_CANVAS_HEIGHT,
  clampCanvasHeight,
  loadCanvasPrefs,
  saveCanvasPrefs,
  type CanvasPrefs,
  type PositionMap,
} from "../layout/manualPositions";

const SAVE_DEBOUNCE_MS = 250;

export interface TreeCanvasPrefs {
  positions: PositionMap;
  height: number;
  /** True when at least one node has been moved by hand. Drives the
   *  enabled state of the "Reset layout" button. */
  hasManualPositions: boolean;
  moveNode: (nodeId: string, x: number, y: number) => void;
  setHeight: (height: number) => void;
  resetLayout: () => void;
}

export function useTreeCanvasPrefs(treeId: string, nodeIds: readonly string[]): TreeCanvasPrefs {
  const [prefs, setPrefs] = useState<CanvasPrefs>(() => loadCanvasPrefs(treeId));

  // Keep the live node ids in a ref so the save effect can prune
  // deleted nodes without re-running on every layout change.
  const nodeIdsRef = useRef<readonly string[]>(nodeIds);
  nodeIdsRef.current = nodeIds;

  useEffect(() => {
    setPrefs(loadCanvasPrefs(treeId));
  }, [treeId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      saveCanvasPrefs(treeId, prefs, nodeIdsRef.current);
    }, SAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [treeId, prefs]);

  const moveNode = useCallback((nodeId: string, x: number, y: number) => {
    setPrefs((prev) => ({
      ...prev,
      positions: { ...prev.positions, [nodeId]: { x, y } },
    }));
  }, []);

  const setHeight = useCallback((height: number) => {
    setPrefs((prev) => {
      const next = clampCanvasHeight(height);
      if (next === prev.height) return prev;
      return { ...prev, height: next };
    });
  }, []);

  const resetLayout = useCallback(() => {
    setPrefs((prev) => ({ ...prev, positions: {} }));
  }, []);

  const hasManualPositions = useMemo(() => {
    const known = new Set(nodeIds);
    return Object.keys(prefs.positions).some((id) => known.has(id));
  }, [prefs.positions, nodeIds]);

  return {
    positions: prefs.positions,
    height: prefs.height || DEFAULT_CANVAS_HEIGHT,
    hasManualPositions,
    moveNode,
    setHeight,
    resetLayout,
  };
}
