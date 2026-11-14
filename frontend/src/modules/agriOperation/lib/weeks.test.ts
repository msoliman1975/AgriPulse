import { describe, expect, it } from "vitest";

import type { PhenologyStage } from "@/api/agriOperation";
import { activityWeek, dayOfYear, seasonLayout, stripEvidenceTags } from "./weeks";

const doy = (code: string, start: string, end: string): PhenologyStage => ({
  code,
  advance: { mode: "calendar_doy", start_doy: start, end_doy: end },
});

const MANGO: PhenologyStage[] = [
  doy("pre_flowering", "12-01", "01-31"),
  doy("flowering", "02-01", "03-15"),
  doy("fruit_set", "03-16", "04-30"),
  doy("post_harvest_flush", "09-16", "11-30"),
];

describe("seasonLayout", () => {
  it("starts a perennial cycle on the first stage and wraps the year", () => {
    const layout = seasonLayout(MANGO, true);
    expect(layout.totalWeeks).toBe(52);
    expect(layout.windows.map((w) => [w.code, w.startWeek, w.endWeek])).toEqual([
      ["pre_flowering", 1, 8],
      ["flowering", 9, 15],
      ["fruit_set", 16, 22],
      ["post_harvest_flush", 42, 52],
    ]);
  });

  it("counts annual stages from planting", () => {
    const layout = seasonLayout(
      [
        { code: "emergence", advance: { mode: "days_from_planting", start_day: 0, end_day: 20 } },
        { code: "vegetative", advance: { mode: "days_from_planting", start_day: 21, end_day: 48 } },
      ],
      false,
    );
    expect(layout.windows.map((w) => [w.startWeek, w.endWeek])).toEqual([
      [1, 3],
      [4, 7],
    ]);
    expect(layout.totalWeeks).toBe(7);
  });

  it("returns no windows when stages don't match the crop's cycle", () => {
    expect(seasonLayout(MANGO, false).windows).toEqual([]);
  });
});

describe("activityWeek", () => {
  const layout = seasonLayout(MANGO, true);
  it("places stage-anchored activities by their offset", () => {
    expect(activityWeek({ anchor: "stage", stage_code: "flowering", offset_days: 7 }, layout)).toBe(
      10,
    );
    expect(activityWeek({ anchor: "stage", stage_code: "fruit_set", offset_days: 0 }, layout)).toBe(
      16,
    );
  });

  it("has no fixed week for start-anchored perennial work or unknown stages", () => {
    expect(activityWeek({ anchor: "start", stage_code: null, offset_days: 0 }, layout)).toBeNull();
    expect(
      activityWeek({ anchor: "stage", stage_code: "nope", offset_days: 0 }, layout),
    ).toBeNull();
  });
});

describe("helpers", () => {
  it("dayOfYear", () => {
    expect(dayOfYear("01-01")).toBe(1);
    expect(dayOfYear("12-31")).toBe(365);
  });

  it("stripEvidenceTags removes tier tags only", () => {
    expect(stripEvidenceTags("Annual N 360 kg/ha. [EG-FAO]")).toBe("Annual N 360 kg/ha.");
    expect(stripEvidenceTags("1st N dose. [EG]/[EG-FAO]")).toBe("1st N dose.");
    expect(stripEvidenceTags("Seed rate. [GENERIC-HIST]")).toBe("Seed rate.");
    expect(stripEvidenceTags("Source [8] · Medium.")).toBe("Source [8] · Medium.");
  });
});
