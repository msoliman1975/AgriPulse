// Grouping a block's cells into areas a person can walk to.
//
// A block of 121 cells must not become 121 rows of detail. Cells that touch
// and hold the same verdict are one area, named by where it sits in the
// block. Mohamed chose geographic grouping over grouping by leaf on
// 2026-09-07, knowing the trade: a scattered verdict makes many small
// groups. The scattered merge below is what keeps that bounded.

import type { StatusCode, Verdict } from "@/api/farmHealth";

/** One cell of a block, with the verdict it holds. */
export interface AreaCell {
  cellId: string;
  row: number;
  col: number;
  status: StatusCode;
  leafNodeId: string;
  verdict: Verdict;
}

export interface Area {
  /** Stable across a date step, so a selection survives the replay. */
  key: string;
  name: AreaName;
  status: StatusCode;
  leafNodeId: string;
  cells: AreaCell[];
  /** Percent of the block, rounded. */
  share: number;
  /** Set when this entry merges the one- and two-cell spots of a leaf. */
  scattered: boolean;
  /** How many separate spots the scattered entry gathered. */
  spots: number;
  /** One verdict from the area; they all say the same thing. */
  sample: Verdict;
}

/**
 * A name is a direction and a size, not a sentence.
 *
 * Returned in parts rather than as text so the caller can translate it. The
 * screen ships in English and Arabic, and a name built by joining English
 * words here would arrive on the Arabic screen in English — which is
 * exactly how this app shipped English under Arabic names once before.
 */
export interface AreaName {
  kind: "whole" | "most" | "direction" | "centre" | "scattered";
  /** One of the eight compass names, when the kind carries one. */
  direction?: "north-west" | "north" | "north-east" | "west" | "east" | "south-west" | "south" | "south-east";
}

const STATUS_RANK: Record<StatusCode, number> = {
  na: 0,
  very_good: 1,
  good: 2,
  issue: 3,
  alert: 4,
};

/** Cells of one leaf that touch on an edge. Four-neighbour flood fill. */
function patches(cells: AreaCell[]): AreaCell[][] {
  const index = new Map<string, AreaCell>();
  for (const cell of cells) index.set(`${cell.row}:${cell.col}`, cell);
  const seen = new Set<string>();
  const groups: AreaCell[][] = [];

  for (const start of cells) {
    const startKey = `${start.row}:${start.col}`;
    if (seen.has(startKey)) continue;
    seen.add(startKey);
    const stack = [start];
    const members: AreaCell[] = [];
    while (stack.length > 0) {
      const cell = stack.pop() as AreaCell;
      members.push(cell);
      for (const [dr, dc] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ]) {
        const key = `${cell.row + dr}:${cell.col + dc}`;
        const neighbour = index.get(key);
        if (neighbour && !seen.has(key) && neighbour.leafNodeId === start.leafNodeId) {
          seen.add(key);
          stack.push(neighbour);
        }
      }
    }
    groups.push(members);
  }
  return groups;
}

/** Where a group sits inside the block's grid. */
function nameOf(members: AreaCell[], rows: number, cols: number, total: number): AreaName {
  if (members.length === total) return { kind: "whole" };

  let sumRow = 0;
  let sumCol = 0;
  for (const cell of members) {
    sumRow += cell.row;
    sumCol += cell.col;
  }
  const fr = sumRow / members.length / Math.max(1, rows - 1);
  const fc = sumCol / members.length / Math.max(1, cols - 1);
  const ns = fr < 0.34 ? "north" : fr > 0.66 ? "south" : "";
  const ew = fc < 0.34 ? "west" : fc > 0.66 ? "east" : "";

  const direction = (
    ns && ew ? `${ns}-${ew}` : ns ? ns : ew ? ew : ""
  ) as AreaName["direction"];

  if (members.length / total >= 0.45) {
    return direction ? { kind: "most", direction } : { kind: "most" };
  }
  if (!direction) return { kind: "centre" };
  return { kind: "direction", direction };
}

/**
 * The areas of one block, worst and largest first.
 *
 * Groups of one or two cells are merged, per leaf, into a single scattered
 * entry. Without that rule a verdict sprinkled across a block produces forty
 * entries, and a list of forty is no more usable than a list of 121.
 */
export function buildAreas(cells: AreaCell[], rows: number, cols: number): Area[] {
  if (cells.length === 0) return [];
  const total = cells.length;

  const byLeaf = new Map<string, AreaCell[]>();
  for (const cell of cells) {
    const list = byLeaf.get(cell.leafNodeId);
    if (list) list.push(cell);
    else byLeaf.set(cell.leafNodeId, [cell]);
  }

  const areas: Area[] = [];
  for (const [leafNodeId, leafCells] of byLeaf) {
    const groups = patches(leafCells);
    const small: AreaCell[][] = [];
    for (const members of groups) {
      if (members.length >= 3) {
        areas.push({
          key: `${leafNodeId}|${members[0].row}:${members[0].col}`,
          name: nameOf(members, rows, cols, total),
          status: members[0].status,
          leafNodeId,
          cells: members,
          share: Math.round((100 * members.length) / total),
          scattered: false,
          spots: 1,
          sample: members[0].verdict,
        });
      } else {
        small.push(members);
      }
    }
    if (small.length > 0) {
      const merged = small.flat();
      areas.push({
        key: `${leafNodeId}|scattered`,
        name: { kind: "scattered" },
        status: merged[0].status,
        leafNodeId,
        cells: merged,
        share: Math.round((100 * merged.length) / total),
        scattered: true,
        spots: small.length,
        sample: merged[0].verdict,
      });
    }
  }

  // Worst first, then largest. The key breaks ties so a replay does not
  // shuffle the chips under the pointer between frames.
  return areas.sort((a, z) => {
    const rank = STATUS_RANK[z.status] - STATUS_RANK[a.status];
    if (rank !== 0) return rank;
    if (z.cells.length !== a.cells.length) return z.cells.length - a.cells.length;
    return a.key.localeCompare(z.key);
  });
}

/**
 * The area to open, given what was open before.
 *
 * Keeping the previous choice is what makes a replay watchable: the date
 * moves and the same patch stays under the eye. When that area is gone —
 * the verdict changed, or the patch split — fall back to the worst one,
 * which is the first.
 */
export function pickArea(areas: Area[], previousKey: string | null): Area | null {
  if (areas.length === 0) return null;
  if (previousKey !== null) {
    const kept = areas.find((area) => area.key === previousKey);
    if (kept) return kept;
  }
  return areas[0];
}
