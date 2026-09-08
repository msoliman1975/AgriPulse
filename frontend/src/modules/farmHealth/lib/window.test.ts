import { describe, expect, it } from "vitest";

import type { StatusCode, Verdict } from "@/api/farmHealth";
import {
  byBlock,
  customWindow,
  dayOf,
  dayOfIso,
  frameMs,
  isoOf,
  rangeWindow,
  verdictsOn,
  windowLength,
  MAX_RANGE_DAYS,
} from "./window";

const TODAY = dayOf(new Date("2026-09-08T00:00:00Z"));

function verdict(
  blockId: string,
  status: StatusCode,
  validFrom: string,
  validTo: string | null,
): Verdict {
  return {
    id: `${blockId}-${validFrom}`,
    farm_id: "farm-1",
    block_id: blockId,
    cell_id: null,
    cell_row: null,
    cell_col: null,
    scope: "block",
    tree_id: "tree-1",
    tree_code: "t_cwsi",
    tree_version: 1,
    leaf_node_id: "leaf_ok",
    kind: "status",
    status_code: status,
    severity: null,
    text_en: "Checked.",
    text_ar: null,
    valid_from: validFrom,
    valid_to: validTo,
    last_evaluated_at: validFrom,
    alert_id: null,
    recommendation_id: null,
  };
}

describe("rangeWindow", () => {
  it("counts both ends, so 30 days is 30 frames", () => {
    const win = rangeWindow("30", TODAY);
    expect(windowLength(win)).toBe(30);
    expect(win.toDay).toBe(TODAY);
  });

  it("covers a year", () => {
    expect(windowLength(rangeWindow("365", TODAY))).toBe(365);
  });
});

describe("customWindow", () => {
  it("takes the two dates as given", () => {
    const win = customWindow("2026-03-01", "2026-06-15", TODAY);
    expect(isoOf(win!.fromDay)).toBe("2026-03-01");
    expect(isoOf(win!.toDay)).toBe("2026-06-15");
  });

  it("clamps an end date in the future, where there are no verdicts", () => {
    const win = customWindow("2026-09-01", "2027-01-01", TODAY);
    expect(isoOf(win!.toDay)).toBe("2026-09-08");
  });

  it("swaps reversed dates rather than refusing them", () => {
    // Someone who typed them the wrong way round meant the range between
    // them. Returning one day would look like a bug in the screen.
    const win = customWindow("2026-09-05", "2026-08-01", TODAY);
    expect(isoOf(win!.fromDay)).toBe("2026-08-01");
    expect(isoOf(win!.toDay)).toBe("2026-09-05");
  });

  it("caps a window that would ask for a decade", () => {
    const win = customWindow("2010-01-01", "2026-09-08", TODAY);
    expect(windowLength(win!)).toBe(MAX_RANGE_DAYS);
  });

  it("is null when a date cannot be read", () => {
    expect(customWindow("", "2026-09-08", TODAY)).toBeNull();
    expect(customWindow("not-a-date", "2026-09-08", TODAY)).toBeNull();
  });
});

describe("isoOf and dayOfIso", () => {
  it("round trip", () => {
    expect(isoOf(dayOfIso("2026-02-29") ?? 0)).toBe("2026-03-01");
    expect(isoOf(dayOfIso("2026-12-31") ?? 0)).toBe("2026-12-31");
  });
});

describe("frameMs", () => {
  it("plays a month at a readable pace", () => {
    expect(frameMs(30, 1)).toBe(828);
  });

  it("plays a year in about the same total time, not five minutes", () => {
    // 365 frames at the month's pace would be five and a half minutes.
    expect(frameMs(365, 1)).toBe(66);
    expect(frameMs(365, 1) * 364).toBeLessThan(30_000);
  });

  it("halves at double speed and never drops below the floor", () => {
    expect(frameMs(30, 2)).toBeLessThan(frameMs(30, 1));
    expect(frameMs(365, 4)).toBe(55);
  });
});

describe("verdictsOn", () => {
  const day = dayOf(new Date("2026-09-05T00:00:00Z"));

  it("keeps a verdict that opened earlier and is still open", () => {
    // This is the common case on a quiet farm. Leaving it out would blank
    // the map for the whole replay.
    const rows = [verdict("b1", "good", "2026-01-01T00:00:00Z", null)];
    expect(verdictsOn(rows, day)).toHaveLength(1);
  });

  it("drops one that closed before the day", () => {
    const rows = [verdict("b1", "alert", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")];
    expect(verdictsOn(rows, day)).toHaveLength(0);
  });

  it("drops one that opens after the day", () => {
    const rows = [verdict("b1", "alert", "2026-09-07T00:00:00Z", null)];
    expect(verdictsOn(rows, day)).toHaveLength(0);
  });

  it("puts a verdict written during the day on that day", () => {
    // Comparing against midnight would push an afternoon sweep onto
    // tomorrow, and the day it was produced would read as empty.
    const rows = [verdict("b1", "issue", "2026-09-05T14:21:00Z", null)];
    expect(verdictsOn(rows, day)).toHaveLength(1);
  });

  it("picks the one interval that covers the day out of a run", () => {
    const rows = [
      verdict("b1", "good", "2026-08-20T00:00:00Z", "2026-09-02T00:00:00Z"),
      verdict("b1", "issue", "2026-09-02T00:00:00Z", "2026-09-07T00:00:00Z"),
      verdict("b1", "alert", "2026-09-07T00:00:00Z", null),
    ];

    expect(verdictsOn(rows, day).map((v) => v.status_code)).toEqual(["issue"]);
  });

  it("carries a value forward on a day with no evaluation", () => {
    // The axis is every calendar day. A gap in the sweep is not a gap in the
    // map; the previous answer still stands.
    const rows = [verdict("b1", "good", "2026-08-30T00:00:00Z", null)];
    const quiet = dayOf(new Date("2026-09-06T00:00:00Z"));
    expect(verdictsOn(rows, quiet).map((v) => v.status_code)).toEqual(["good"]);
  });
});

describe("byBlock", () => {
  it("gathers a day's verdicts under their blocks", () => {
    const grouped = byBlock([
      verdict("b1", "good", "2026-09-01T00:00:00Z", null),
      verdict("b2", "alert", "2026-09-01T00:00:00Z", null),
      verdict("b1", "issue", "2026-09-01T00:00:00Z", null),
    ]);

    expect([...grouped.keys()].sort()).toEqual(["b1", "b2"]);
    expect(grouped.get("b1")).toHaveLength(2);
  });
});
