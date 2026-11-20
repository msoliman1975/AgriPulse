import { describe, expect, it } from "vitest";

import { occurrenceOffsets } from "./occurrences";

// Same cases as the server's test_occurrence_offsets_spacing.
describe("occurrenceOffsets", () => {
  it("matches the server's spacing", () => {
    expect(occurrenceOffsets(56, null, null)).toEqual([0]);
    expect(occurrenceOffsets(28, 2, "week")).toEqual([0, 3, 7, 10, 14, 17, 21, 24]);
    expect(occurrenceOffsets(7, 7, "week")).toEqual([0, 1, 2, 3, 4, 5, 6]);
    const monthly = occurrenceOffsets(365, 1, "month");
    expect(monthly).toHaveLength(12);
    expect(monthly[1]).toBe(30);
    expect(monthly[11]).toBe(334);
    expect(occurrenceOffsets(91, 2, "month")).toEqual([0, 15, 30, 45, 60, 76]);
    expect(occurrenceOffsets(35, 2, "season")).toEqual([0, 17]);
    expect(occurrenceOffsets(5, 1, "month")).toEqual([0]);
  });
});
