import { describe, expect, it } from "vitest";

import type { AllocatedActivityPreview, AllocationBlockSchedule } from "@/api/agriOperation";
import { calendarWeeks, groupWeeksByStage } from "./calendarWeeks";

const act = (key: string, date: string): AllocatedActivityPreview => ({
  activity_key: key,
  source: "template",
  template_activity_id: null,
  activity_type: "irrigation",
  title: key,
  title_ar: null,
  scheduled_date: date,
  default_date: date,
  date_overridden: false,
  duration_days: 1,
  anchored_stage_code: null,
  product_name: null,
  dosage: null,
  notes: null,
});

const block = (
  id: string,
  start: string,
  acts: AllocatedActivityPreview[],
): AllocationBlockSchedule => ({
  block_id: id,
  block_code: id,
  crop_path: "mango",
  start_date: start,
  activities: acts,
  skipped: [],
});

describe("calendarWeeks", () => {
  it("lists every week from the start to the last task, empty ones too", () => {
    const weeks = calendarWeeks([
      block("b1", "2027-01-04", [
        act("irrigation-1#2", "2027-01-20"),
        act("irrigation-1", "2027-01-04"),
      ]),
    ]);
    expect(weeks.map((w) => [w.number, w.from, w.to, w.items.length])).toEqual([
      [1, "2027-01-04", "2027-01-10", 1],
      [2, "2027-01-11", "2027-01-17", 0],
      [3, "2027-01-18", "2027-01-24", 1],
    ]);
  });

  it("counts Week 1 from the first task, even before the start, and merges blocks", () => {
    const weeks = calendarWeeks([
      block("b1", "2027-03-01", [act("soil_prep-1", "2027-02-15")]),
      block("b2", "2027-03-08", [act("planting-1", "2027-03-01")]),
    ]);
    expect(weeks.map((w) => [w.number, w.from])).toEqual([
      [1, "2027-02-15"],
      [2, "2027-02-22"],
      [3, "2027-03-01"],
    ]);
    expect(weeks[2]?.items.map((i) => i.blockId)).toEqual(["b2"]);
    expect(weeks[0]?.items.map((i) => i.activity.activity_key)).toEqual(["soil_prep-1"]);
  });

  it("is empty with nothing scheduled", () => {
    expect(calendarWeeks([block("b1", "2027-01-04", [])])).toEqual([]);
  });

  it("lists a task in every week of its window, dated only where a time falls", () => {
    const once = {
      ...act("prune-1", "2027-01-05"),
      activity_code: "prune-1",
      window_start: "2027-01-04",
      window_end: "2027-01-24",
    };
    const times = ["2027-01-04", "2027-01-18"].map((d, i) => ({
      ...act(i === 0 ? "irr-1" : "irr-1#2", d),
      activity_code: "irr-1",
      occurrence: i + 1,
      occurrences: 2,
      repeat_count: 1,
      repeat_unit: "month",
      window_start: "2027-01-04",
      window_end: "2027-01-24",
    }));
    const weeks = calendarWeeks([block("b1", "2027-01-04", [once, ...times])]);
    expect(weeks.map((w) => w.items.map((i) => i.activity.activity_key))).toEqual([
      ["irr-1", "prune-1"],
      [],
      ["irr-1#2"],
    ]);
    expect(
      weeks.map((w) =>
        w.spans.map((s) => [s.activity.activity_key, s.firstWeek, s.lastWeek, s.nextDate]),
      ),
    ).toEqual([
      [],
      [
        ["irr-1", 1, 3, "2027-01-18"],
        ["prune-1", 1, 3, null],
      ],
      [["prune-1", 1, 3, null]],
    ]);
  });
});

describe("groupWeeksByStage", () => {
  it("groups consecutive weeks under the stage their first day falls in", () => {
    const weeks = calendarWeeks([
      block("b1", "2027-01-04", [act("a", "2027-01-04"), act("b", "2027-01-25")]),
    ]);
    const stage = (code: string, start: string, end: string) => ({
      code,
      name_en: code,
      name_ar: null,
      start_date: start,
      end_date: end,
    });
    const groups = groupWeeksByStage(weeks, [
      stage("flowering", "2027-01-01", "2027-01-13"),
      stage("fruit_set", "2027-01-14", "2027-01-20"),
    ]);
    expect(groups.map((g) => [g.stage?.code ?? null, g.weeks.map((w) => w.number)])).toEqual([
      ["flowering", [1, 2]],
      ["fruit_set", [3]],
      [null, [4]],
    ]);
  });
});
