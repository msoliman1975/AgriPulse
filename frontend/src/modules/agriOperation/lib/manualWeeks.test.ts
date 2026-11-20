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

  it("keeps tasks with no week apart", () => {
    const perennial = seasonLayout(
      [{ code: "flower", advance: { mode: "calendar_doy", start_doy: "01-15" } }],
      true,
    );
    const { unplaced } = manualWeeks(perennial, [act("x", { anchor: "start", stage_code: null })]);
    expect(unplaced.map((a) => a.code)).toEqual(["x"]);
  });
});
