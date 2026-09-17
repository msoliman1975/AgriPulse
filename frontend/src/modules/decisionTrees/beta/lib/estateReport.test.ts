// The estate report's screen-side arithmetic.
//
// Sorting and formatting are pure, so they are pinned here rather than read
// off a rendered table. The two judgements the screen makes — how loudly to
// say the error count, and whether the combination rules are being bypassed —
// are the reason this file exists: both change what an agronomist decides.

import { describe, expect, it } from "vitest";

import type { EstateFindingSet, EstateReport } from "./estateApi";
import {
  BLOCKING_ERROR_PCT,
  errorBand,
  formatCount,
  formatDuration,
  formatPct,
  formatPerCell,
  rulesAreBypassed,
  setLabel,
  sortFindingSets,
} from "./estateReport";

function set(label: string, count: number, rule: string | null = null): EstateFindingSet {
  return {
    codes: label.replace(/[{}]/g, "").split(", ").filter(Boolean),
    label,
    count,
    share_pct: 0,
    matched_rule: rule,
    composed: rule === null,
    composed_count: rule === null ? count : 0,
    blocks: 1,
    status: null,
    severity: null,
    action_type: null,
    text_en: null,
  };
}

describe("sortFindingSets", () => {
  const rows = [set("{dry}", 204), set("{ndvi_low}", 96, "r3"), set("{pest_high}", 118)];

  it("puts the commonest set first by default", () => {
    const sorted = sortFindingSets(rows, "count", "desc");
    expect(sorted.map((r) => r.label)).toEqual(["{dry}", "{pest_high}", "{ndvi_low}"]);
  });

  it("reverses on ascending", () => {
    const sorted = sortFindingSets(rows, "count", "asc");
    expect(sorted.map((r) => r.label)).toEqual(["{ndvi_low}", "{pest_high}", "{dry}"]);
  });

  it("sorts by label", () => {
    const sorted = sortFindingSets(rows, "label", "asc");
    expect(sorted.map((r) => r.label)).toEqual(["{dry}", "{ndvi_low}", "{pest_high}"]);
  });

  it("groups the composed rows after the rules", () => {
    const sorted = sortFindingSets(rows, "rule", "asc");
    expect(sorted[0].matched_rule).toBe("r3");
    expect(sorted.slice(1).every((r) => r.matched_rule === null)).toBe(true);
  });

  it("does not modify its input", () => {
    const original = [...rows];
    sortFindingSets(rows, "label", "asc");
    expect(rows).toEqual(original);
  });
});

describe("errorBand", () => {
  it("says none when no cell errored", () => {
    expect(errorBand({ cells_errored: 0, cells_errored_pct: 0 })).toBe("none");
  });

  it("says some below the blocking share", () => {
    expect(errorBand({ cells_errored: 12, cells_errored_pct: 1.2 })).toBe("some");
  });

  it("says blocking at the share and above", () => {
    expect(errorBand({ cells_errored: 400, cells_errored_pct: BLOCKING_ERROR_PCT })).toBe(
      "blocking",
    );
    expect(errorBand({ cells_errored: 900, cells_errored_pct: 41.2 })).toBe("blocking");
  });
});

describe("rulesAreBypassed", () => {
  it("is true when rules exist, cells carded, and none fired", () => {
    const report: EstateReport = { rules_defined: 6, rules_fired: 0, cells_carded: 71 };
    expect(rulesAreBypassed(report)).toBe(true);
  });

  it("is false when a rule fired", () => {
    expect(rulesAreBypassed({ rules_defined: 6, rules_fired: 2, cells_carded: 71 })).toBe(false);
  });

  it("is false when the tree defines no rules at all", () => {
    // Nothing is being bypassed: the author wrote no rule to bypass.
    expect(rulesAreBypassed({ rules_defined: 0, rules_fired: 0, cells_carded: 71 })).toBe(false);
  });

  // "cards" rather than "card": an eslint rule forbids the bare word,
  // which was a retired CSS layer name.
  it("is false when no cell produced cards", () => {
    expect(rulesAreBypassed({ rules_defined: 6, rules_fired: 0, cells_carded: 0 })).toBe(false);
  });
});

describe("formatting", () => {
  it("gives seconds over a second and milliseconds under one", () => {
    expect(formatDuration(18_400)).toBe("18.4 s");
    expect(formatDuration(430)).toBe("430 ms");
    expect(formatDuration(null)).toBe("—");
  });

  it("gives one decimal for the per-cell figure", () => {
    expect(formatPerCell(4.3)).toBe("4.3 ms");
    expect(formatPerCell(undefined)).toBe("—");
  });

  it("gives one decimal for a percentage, always", () => {
    expect(formatPct(87.7)).toBe("87.7%");
    expect(formatPct(88)).toBe("88.0%");
  });

  it("groups thousands", () => {
    expect(formatCount(4312, "en")).toBe("4,312");
    expect(formatCount(null, "en")).toBe("—");
  });

  it("writes a set the way the report does", () => {
    expect(setLabel(["ndvi_low", "dry"])).toBe("{dry, ndvi_low}");
    expect(setLabel([])).toBe("{}");
  });
});
