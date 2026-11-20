import { describe, expect, it } from "vitest";

import type { PhenologyStage } from "@/api/agriOperation";
import type { PlanTemplateActivity } from "@/api/planTemplates";
import { manualWeeks } from "./manualWeeks";
import { seasonLayout } from "./weeks";

const stage = (code: string, start: number, end?: number): PhenologyStage => ({
  code,
  name_en: code,
  advance: { mode: "days_from_planting", start_day: start, ...(end ? { end_day: end } : {}) },
});

const act = (code: string, over: Partial<PlanTemplateActivity>): PlanTemplateActivity => ({
  id: code,
  code,
  activity_type: "irrigation",
  anchor: "stage",
  milestone_id: null,
  stage_code: "veg",
  offset_days: 0,
  duration_days: 1,
  product_name: null,
  dosage: null,
  notes: null,
  start_time: null,
  sort_order: 0,
  ...over,
});

describe("manualWeeks", () => {
  const layout = seasonLayout([stage("veg", 0, 20), stage("bulking", 21, 34)], false);

  it("lists every week of each stage with every task active in it", () => {
    const { groups, unplaced } = manualWeeks(layout, [
      act("weed", { duration_days: 14 }),
      act("irr", { duration_days: 21, repeat_count: 1, repeat_unit: "week" }),
      act("spray", { stage_code: "bulking", offset_days: 7 }),
      act("fert", { stage_code: "veg", duration_days: 21, repeat_count: 1, repeat_unit: "season" }),
    ]);
    expect(unplaced).toEqual([]);
    expect(groups.map((g) => [g.window?.code, g.weeks.map((w) => w.week)])).toEqual([
      ["veg", [1, 2, 3]],
      ["bulking", [4, 5]],
    ]);
    const veg = groups[0].weeks.map((w) =>
      w.tasks.map((t) => [t.activity.code, t.firstWeek, t.lastWeek, t.timesThisWeek]),
    );
    expect(veg[0]).toEqual([
      ["weed", 1, 2, null],
      ["irr", 1, 3, 1],
      ["fert", 1, 3, 1],
    ]);
    // Weeding is done once in weeks 1–2; fertiliser once in the window, not in week 3.
    expect(veg[2]).toEqual([
      ["irr", 1, 3, 1],
      ["fert", 1, 3, 0],
    ]);
    expect(groups[1].weeks.map((w) => w.tasks.map((t) => t.activity.code))).toEqual([
      [],
      ["spray"],
    ]);
  });

  it("keeps start-date tasks apart in a manual laid out by stage", () => {
    const perennial = seasonLayout(
      [{ code: "flower", advance: { mode: "calendar_doy", start_doy: "01-15" } }],
      true,
    );
    const { mode, unplaced } = manualWeeks(perennial, [
      act("s", { stage_code: "flower" }),
      act("x", { anchor: "start", stage_code: null }),
    ]);
    expect(mode).toBe("stages");
    expect(unplaced.map((a) => a.code)).toEqual(["x"]);
  });

  it("counts a start-date manual from its first task, by year", () => {
    const perennial = seasonLayout(
      [{ code: "flower", advance: { mode: "calendar_doy", start_doy: "01-15" } }],
      true,
    );
    const r = manualWeeks(perennial, [
      act("holes", { anchor: "start", stage_code: null, offset_days: -56, duration_days: 28 }),
      act("plant", { anchor: "start", stage_code: null, offset_days: 0, duration_days: 7 }),
      act("irr", {
        anchor: "start",
        stage_code: null,
        offset_days: 365,
        duration_days: 14,
        repeat_count: 1,
        repeat_unit: "week",
      }),
    ]);
    expect(r.mode).toBe("start");
    expect(r.unplaced).toEqual([]);
    expect(r.groups.map((g) => [g.year, g.weeks[0]?.week, g.weeks.at(-1)?.week])).toEqual([
      [1, 1, 52],
      [2, 53, 62],
    ]);
    const weeks = r.groups.flatMap((g) => g.weeks);
    const codes = (n: number) => weeks.find((w) => w.week === n)?.tasks.map((t) => t.activity.code);
    // Holes are dug in weeks 1-4; planting falls in week 9; year-2 irrigation weekly.
    expect(codes(1)).toEqual(["holes"]);
    expect(codes(4)).toEqual(["holes"]);
    expect(codes(5)).toEqual([]);
    expect(codes(9)).toEqual(["plant"]);
    expect(weeks.find((w) => w.week === 61)?.tasks[0]?.timesThisWeek).toBe(1);
  });
});
