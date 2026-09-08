import { describe, expect, it } from "vitest";

import type { StatusCode, Verdict } from "@/api/farmHealth";
import { buildAreas, pickArea, type AreaCell } from "./areas";

function verdictFor(cellId: string, status: StatusCode, leaf: string): Verdict {
  return {
    id: `v-${cellId}`,
    farm_id: "farm-1",
    block_id: "b1",
    cell_id: cellId,
    cell_row: 0,
    cell_col: 0,
    scope: "cell",
    tree_id: "tree-1",
    tree_code: "t_cwsi",
    tree_version: 1,
    leaf_node_id: leaf,
    kind: "status",
    status_code: status,
    severity: null,
    text_en: "Checked.",
    text_ar: null,
    valid_from: "2026-09-01T00:00:00Z",
    valid_to: null,
    last_evaluated_at: "2026-09-07T00:00:00Z",
    alert_id: null,
    recommendation_id: null,
  };
}

function cell(row: number, col: number, status: StatusCode, leaf = `leaf_${status}`): AreaCell {
  const cellId = `${row}:${col}`;
  return { cellId, row, col, status, leafNodeId: leaf, verdict: verdictFor(cellId, status, leaf) };
}

/** A rows x cols block where every cell holds the same verdict. */
function uniform(rows: number, cols: number, status: StatusCode): AreaCell[] {
  const cells: AreaCell[] = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) cells.push(cell(r, c, status));
  }
  return cells;
}

describe("buildAreas", () => {
  it("calls one verdict over the whole block by its name", () => {
    const areas = buildAreas(uniform(3, 3, "good"), 3, 3);

    expect(areas).toHaveLength(1);
    expect(areas[0].name).toEqual({ kind: "whole" });
    expect(areas[0].share).toBe(100);
  });

  it("splits two groups of the same verdict that do not touch", () => {
    const cells = [...uniform(5, 5, "good")];
    for (const [r, c] of [
      [0, 0],
      [0, 1],
      [0, 2],
      [4, 4],
      [4, 3],
      [3, 4],
    ]) {
      const at = cells.findIndex((x) => x.row === r && x.col === c);
      cells[at] = cell(r, c, "alert");
    }

    const areas = buildAreas(cells, 5, 5);
    const alerts = areas.filter((a) => a.status === "alert");

    // Two separate corners, not one area of six cells.
    expect(alerts).toHaveLength(2);
    expect(alerts.every((a) => !a.scattered)).toBe(true);
  });

  it("merges one- and two-cell spots into one scattered entry", () => {
    // Without this rule a sprinkled verdict makes an entry per speck, and a
    // list of forty is no more usable than a list of 121.
    const cells = [...uniform(5, 5, "good")];
    for (const [r, c] of [
      [0, 0],
      [2, 2],
      [4, 4],
    ]) {
      const at = cells.findIndex((x) => x.row === r && x.col === c);
      cells[at] = cell(r, c, "alert");
    }

    const areas = buildAreas(cells, 5, 5);
    const alerts = areas.filter((a) => a.status === "alert");

    expect(alerts).toHaveLength(1);
    expect(alerts[0].scattered).toBe(true);
    expect(alerts[0].spots).toBe(3);
    expect(alerts[0].cells).toHaveLength(3);
  });

  it("keeps a group of three as a patch, not as scatter", () => {
    const cells = [...uniform(5, 5, "good")];
    for (const [r, c] of [
      [0, 0],
      [0, 1],
      [1, 0],
    ]) {
      const at = cells.findIndex((x) => x.row === r && x.col === c);
      cells[at] = cell(r, c, "alert");
    }

    const areas = buildAreas(cells, 5, 5);
    const alert = areas.find((a) => a.status === "alert");

    expect(alert?.scattered).toBe(false);
    expect(alert?.name).toEqual({ kind: "direction", direction: "north-west" });
  });

  it("names a group by where it sits in the block", () => {
    const cells = [...uniform(9, 9, "good")];
    for (let r = 6; r < 9; r += 1) {
      for (let c = 6; c < 9; c += 1) {
        const at = cells.findIndex((x) => x.row === r && x.col === c);
        cells[at] = cell(r, c, "issue");
      }
    }

    const areas = buildAreas(cells, 9, 9);
    const issue = areas.find((a) => a.status === "issue");

    expect(issue?.name).toEqual({ kind: "direction", direction: "south-east" });
  });

  it("calls a group covering nearly half the block most of it", () => {
    const cells = [...uniform(4, 4, "good")];
    for (let r = 0; r < 2; r += 1) {
      for (let c = 0; c < 4; c += 1) {
        const at = cells.findIndex((x) => x.row === r && x.col === c);
        cells[at] = cell(r, c, "alert");
      }
    }

    const areas = buildAreas(cells, 4, 4);
    const alert = areas.find((a) => a.status === "alert");

    expect(alert?.name.kind).toBe("most");
    expect(alert?.share).toBe(50);
  });

  it("puts the worst area first, then the largest", () => {
    const cells = [...uniform(6, 6, "good")];
    // three alert cells in a row, and a bigger issue block
    for (const [r, c] of [
      [0, 0],
      [0, 1],
      [0, 2],
    ]) {
      const at = cells.findIndex((x) => x.row === r && x.col === c);
      cells[at] = cell(r, c, "alert");
    }
    for (let r = 3; r < 6; r += 1) {
      for (let c = 0; c < 4; c += 1) {
        const at = cells.findIndex((x) => x.row === r && x.col === c);
        cells[at] = cell(r, c, "issue");
      }
    }

    const areas = buildAreas(cells, 6, 6);

    // Alert outranks issue even though the issue area is four times larger.
    expect(areas[0].status).toBe("alert");
    expect(areas[1].status).toBe("issue");
  });

  it("separates two verdicts that touch", () => {
    // Neighbouring cells with different leaves are different areas, however
    // adjacent they are.
    const areas = buildAreas(
      [cell(0, 0, "good"), cell(0, 1, "good"), cell(0, 2, "good"), cell(1, 0, "alert"), cell(1, 1, "alert"), cell(1, 2, "alert")],
      2,
      3,
    );

    expect(areas).toHaveLength(2);
    expect(areas.map((a) => a.status)).toEqual(["alert", "good"]);
  });

  it("separates two leaves that reached the same status", () => {
    // Two routes can end at the same colour for different reasons. Grouping
    // them together would put one explanation over both.
    const areas = buildAreas(
      [
        cell(0, 0, "issue", "leaf_band"),
        cell(0, 1, "issue", "leaf_band"),
        cell(0, 2, "issue", "leaf_band"),
        cell(1, 0, "issue", "leaf_baseline"),
        cell(1, 1, "issue", "leaf_baseline"),
        cell(1, 2, "issue", "leaf_baseline"),
      ],
      2,
      3,
    );

    expect(areas).toHaveLength(2);
    expect(areas.map((a) => a.leafNodeId).sort()).toEqual(["leaf_band", "leaf_baseline"]);
  });

  it("is empty for a block with no cells", () => {
    expect(buildAreas([], 0, 0)).toEqual([]);
  });
});

describe("pickArea", () => {
  const areas = buildAreas(
    [cell(0, 0, "alert"), cell(0, 1, "alert"), cell(0, 2, "alert"), cell(1, 0, "good"), cell(1, 1, "good"), cell(1, 2, "good")],
    2,
    3,
  );

  it("opens the worst area when nothing was chosen", () => {
    expect(pickArea(areas, null)?.status).toBe("alert");
  });

  it("keeps the area that was open, so a replay stays on one patch", () => {
    const good = areas.find((a) => a.status === "good");
    expect(pickArea(areas, good!.key)?.key).toBe(good!.key);
  });

  it("falls back to the worst when the chosen area is gone", () => {
    expect(pickArea(areas, "leaf_that_vanished|0:0")?.status).toBe("alert");
  });

  it("is null when the block has no areas", () => {
    expect(pickArea([], "anything")).toBeNull();
  });
});
