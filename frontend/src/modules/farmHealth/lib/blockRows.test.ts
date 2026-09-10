import { describe, expect, it } from "vitest";

import type { BlockVerdicts, StatusCode, StatusDefinition, Verdict } from "@/api/farmHealth";
import { buildBlockRows, treeOptions, type BlockMeta } from "./blockRows";

const STATUSES: StatusDefinition[] = [
  { code: "na", rank: 0, color: "#9AA0A6", label_en: "Not assessed", label_ar: "لا ينطبق" },
  { code: "very_good", rank: 1, color: "#1B873F", label_en: "Very good", label_ar: "ممتاز" },
  { code: "good", rank: 2, color: "#6FBF4B", label_en: "Good", label_ar: "جيد" },
  { code: "issue", rank: 3, color: "#E8A33D", label_en: "Issue", label_ar: "مشكلة" },
  { code: "alert", rank: 4, color: "#D64545", label_en: "Alert", label_ar: "إنذار" },
];

function verdict(blockId: string, treeCode: string, status: StatusCode, cell?: number): Verdict {
  return {
    id: `${blockId}-${treeCode}-${status}-${cell ?? "block"}`,
    farm_id: "farm-1",
    block_id: blockId,
    cell_id: cell === undefined ? null : `cell-${cell}`,
    cell_row: cell === undefined ? null : cell,
    cell_col: cell === undefined ? null : 1,
    scope: cell === undefined ? "block" : "cell",
    tree_id: `tree-${treeCode}`,
    tree_code: treeCode,
    tree_name_en: null,
    tree_name_ar: null,
    tree_version: 1,
    leaf_node_id: "leaf_ok",
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

function farmBlock(blockId: string, verdicts: Verdict[]): BlockVerdicts {
  return {
    block_id: blockId,
    as_of: null,
    worst_status: null,
    last_evaluated_at: null,
    verdicts,
  };
}

const BLOCKS: BlockMeta[] = [
  { id: "b1", code: "AG-R01-C01", crop_name: "Mango" },
  { id: "b2", code: "AG-R01-C02", crop_name: "Mango" },
  { id: "b3", code: "AG-R02-C01", crop_name: "Mango" },
];

describe("buildBlockRows", () => {
  it("orders the rail worst first", () => {
    const rows = buildBlockRows(
      BLOCKS,
      [
        farmBlock("b1", [verdict("b1", "cwsi", "good")]),
        farmBlock("b2", [verdict("b2", "cwsi", "alert")]),
        farmBlock("b3", [verdict("b3", "cwsi", "issue")]),
      ],
      "cwsi",
      STATUSES,
    );

    expect(rows.map((r) => r.code)).toEqual(["AG-R01-C02", "AG-R02-C01", "AG-R01-C01"]);
    expect(rows.map((r) => r.worst)).toEqual(["alert", "issue", "good"]);
  });

  it("counts each status, so one bad cell does not hide behind many good ones", () => {
    const rows = buildBlockRows(
      BLOCKS.slice(0, 1),
      [
        farmBlock("b1", [
          verdict("b1", "cwsi", "good", 1),
          verdict("b1", "cwsi", "good", 2),
          verdict("b1", "cwsi", "alert", 3),
        ]),
      ],
      "cwsi",
      STATUSES,
    );

    expect(rows[0].counts).toMatchObject({ good: 2, alert: 1, issue: 0 });
    // The block reads as its worst cell, not its most common one.
    expect(rows[0].worst).toBe("alert");
  });

  it("keeps a block the tree never ran on, and marks it", () => {
    // The farm read omits such a block entirely. Dropping it from the rail
    // too would hide the state this screen exists to show.
    const rows = buildBlockRows(BLOCKS, [farmBlock("b1", [verdict("b1", "cwsi", "good")])], "cwsi", STATUSES);

    expect(rows).toHaveLength(3);
    const missing = rows.filter((r) => r.didNotRun).map((r) => r.code);
    expect(missing).toEqual(["AG-R01-C02", "AG-R02-C01"]);
    expect(rows.find((r) => r.code === "AG-R01-C02")?.worst).toBeNull();
  });

  it("a block the tree did not run on sorts last, below every reading", () => {
    const rows = buildBlockRows(
      BLOCKS,
      [
        farmBlock("b1", [verdict("b1", "cwsi", "na")]),
        farmBlock("b3", [verdict("b3", "cwsi", "very_good")]),
      ],
      "cwsi",
      STATUSES,
    );

    // `na` means the tree ran and could not assess. That still outranks an
    // absent row, which means it never ran at all.
    expect(rows.map((r) => r.code)).toEqual(["AG-R02-C01", "AG-R01-C01", "AG-R01-C02"]);
    expect(rows[2].didNotRun).toBe(true);
  });

  it("shows only the selected tree", () => {
    const rows = buildBlockRows(
      BLOCKS.slice(0, 1),
      [farmBlock("b1", [verdict("b1", "cwsi", "alert"), verdict("b1", "ndvi", "good")])],
      "ndvi",
      STATUSES,
    );

    expect(rows[0].verdicts).toHaveLength(1);
    expect(rows[0].worst).toBe("good");
  });

  it("keeps the order stable when two blocks read the same", () => {
    // A replay re-sorts on every frame. Ties that break on insertion order
    // make rows jump under the pointer.
    const rows = buildBlockRows(
      BLOCKS,
      [
        farmBlock("b3", [verdict("b3", "cwsi", "issue")]),
        farmBlock("b1", [verdict("b1", "cwsi", "issue")]),
        farmBlock("b2", [verdict("b2", "cwsi", "issue")]),
      ],
      "cwsi",
      STATUSES,
    );

    expect(rows.map((r) => r.code)).toEqual(["AG-R01-C01", "AG-R01-C02", "AG-R02-C01"]);
  });
});

describe("treeOptions", () => {
  it("lists only trees that said something about this farm", () => {
    const options = treeOptions([
      farmBlock("b1", [verdict("b1", "ndvi", "good"), verdict("b1", "cwsi", "alert")]),
      farmBlock("b2", [verdict("b2", "cwsi", "good")]),
    ]);

    expect(options).toEqual([
      { code: "cwsi", count: 2, label: "cwsi" },
      { code: "ndvi", count: 1, label: "ndvi" },
    ]);
  });

  it("is empty when no tree has run on the farm", () => {
    expect(treeOptions([])).toEqual([]);
  });

  it("labels a tree by its name, and sorts by the name a reader sees", () => {
    // The picker showed `t_cwsi` and `t_ndvi`. Sorting by code then reads as
    // unsorted once the codes are hidden, so the order follows the label.
    const named = (code: string, nameEn: string, nameAr: string | null) => ({
      ...verdict("b1", code, "good"),
      tree_name_en: nameEn,
      tree_name_ar: nameAr,
    });
    const options = treeOptions([
      farmBlock("b1", [
        named("z_water", "Almond water stress", "إجهاد مائي للوز"),
        named("a_canopy", "Mango canopy health", "صحة مجموع المانجو"),
      ]),
    ]);

    expect(options.map((option) => option.label)).toEqual([
      "Almond water stress",
      "Mango canopy health",
    ]);
    // The value the rail filters on is still the code.
    expect(options.map((option) => option.code)).toEqual(["z_water", "a_canopy"]);
  });

  it("chooses the Arabic name, and falls back rather than showing nothing", () => {
    const options = treeOptions(
      [
        farmBlock("b1", [
          {
            ...verdict("b1", "cwsi", "good"),
            tree_name_en: "Water stress",
            tree_name_ar: "إجهاد مائي",
          },
          { ...verdict("b1", "ndvi", "good"), tree_name_en: "Canopy", tree_name_ar: null },
          // An older API sends no name at all. The code is what is left.
          verdict("b1", "smi", "good"),
        ]),
      ],
      true,
    );

    expect(options.map((option) => option.label).sort()).toEqual(
      ["Canopy", "smi", "إجهاد مائي"].sort(),
    );
  });
});
