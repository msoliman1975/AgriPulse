import { describe, expect, it } from "vitest";

import type { AllocatedActivityPreview, AllocationBlockSchedule } from "@/api/agriOperation";
import { calendarWeeks } from "./calendarWeeks";

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
): AllocationBlockSchedule =>
  ({
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

  it("counts weeks before the start as negative and merges blocks by date", () => {
    const weeks = calendarWeeks([
      block("b1", "2027-03-01", [act("soil_prep-1", "2027-02-15")]),
      block("b2", "2027-03-08", [act("planting-1", "2027-03-01")]),
    ]);
    expect(weeks.map((w) => w.number)).toEqual([-2, -1, 1]);
    expect(weeks[2]?.items.map((i) => i.blockId)).toEqual(["b2"]);
    expect(weeks[0]?.items.map((i) => i.activity.activity_key)).toEqual(["soil_prep-1"]);
  });

  it("is empty with nothing scheduled", () => {
    expect(calendarWeeks([block("b1", "2027-01-04", [])])).toEqual([]);
  });
});
