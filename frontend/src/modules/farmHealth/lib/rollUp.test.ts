// The Farm Health rollup, against the cases the backend rollup is pinned by
// (`backend/tests/unit/shared/test_health_cell_rollup.py`). Ten cells in
// each, so a share is a count: 2 of 10 is 20%.

import { describe, expect, it } from "vitest";

import type { StatusCode, Verdict } from "@/api/farmHealth";

import { DEFAULT_RULE, rollUp, rulesFrom, type CellRule } from "./blockRows";

function cells(counts: Partial<Record<StatusCode, number>>, tree = "t"): Verdict[] {
  const out: Verdict[] = [];
  let n = 0;
  for (const [code, count] of Object.entries(counts)) {
    for (let i = 0; i < (count ?? 0); i += 1) {
      out.push({ cell_id: `c${n}`, status_code: code, tree_code: tree } as unknown as Verdict);
      n += 1;
    }
  }
  return out;
}

const SHARE: CellRule = { rule: "share", share: 0.2 };
const MOST: CellRule = { rule: "most_common", share: null };

describe("rollUp", () => {
  it("worst: one alert cell makes the block alert", () => {
    expect(rollUp(cells({ alert: 1, good: 9 }), DEFAULT_RULE)).toBe("alert");
  });

  it("share: one alert cell of ten does not recolour the block", () => {
    expect(rollUp(cells({ alert: 1, good: 9 }), SHARE)).toBe("good");
  });

  it("share: two alert cells of ten do", () => {
    expect(rollUp(cells({ alert: 2, good: 8 }), SHARE)).toBe("alert");
  });

  it("share: worse statuses count toward a milder one", () => {
    expect(rollUp(cells({ alert: 1, issue: 1, good: 8 }), SHARE)).toBe("issue");
  });

  it("share: reads the share it is given", () => {
    const three = cells({ alert: 3, good: 7 });
    expect(rollUp(three, { rule: "share", share: 0.5 })).toBe("good");
    expect(rollUp(three, { rule: "share", share: 0.3 })).toBe("alert");
  });

  it("a whole-block verdict counts in full", () => {
    const block = { cell_id: null, status_code: "alert", tree_code: "b" } as unknown as Verdict;
    expect(rollUp([...cells({ good: 10 }), block], SHARE)).toBe("alert");
  });

  it("a cell two trees judged counts once, at its worst", () => {
    const water = cells({ good: 10 }, "water");
    const alarm = {
      cell_id: "c0",
      status_code: "alert",
      tree_code: "vigour",
    } as unknown as Verdict;
    expect(rollUp([...water, alarm], SHARE)).toBe("good");
    expect(rollUp([...water, alarm], DEFAULT_RULE)).toBe("alert");
  });

  it("most_common: the status on most cells, a tie to the worse", () => {
    expect(rollUp(cells({ alert: 3, good: 7 }), MOST)).toBe("good");
    expect(rollUp(cells({ issue: 5, good: 5 }), MOST)).toBe("issue");
  });

  it("no verdicts is no status, not a status", () => {
    expect(rollUp([], SHARE)).toBeNull();
  });

  it("a block the farm read sends no rule for uses the default", () => {
    const rules = rulesFrom([
      {
        block_id: "b1",
        as_of: null,
        worst_status: null,
        last_evaluated_at: null,
        verdicts: [],
        cell_rollup: "share",
        cell_share: 0.35,
      },
    ]);
    expect(rules.get("b1")).toEqual({ rule: "share", share: 0.35 });
    expect(rules.get("b2") ?? DEFAULT_RULE).toEqual(DEFAULT_RULE);
  });
});
