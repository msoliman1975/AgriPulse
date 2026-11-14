import { describe, expect, it } from "vitest";

import type { PlanTemplateDetail } from "@/api/planTemplates";
import {
  activityArabicMissing,
  draftFromDetail,
  emptyManual,
  manualProblems,
  newActivity,
  toWriteRequest,
} from "./manualDraft";

const detail = {
  id: "t1",
  code: "mango-keitt-eg",
  name: "Mango — Keitt",
  name_ar: "مانجو كيت",
  crop_path: "mango.keitt",
  crop_id: null,
  country: "EG",
  region: null,
  description: null,
  description_ar: null,
  status: "draft",
  revision: 2,
  published_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  activity_count: 2,
  milestones: [
    {
      id: "m1",
      code: "harvest",
      name: "Harvest",
      name_ar: null,
      day_from_start: 200,
      sort_order: 0,
    },
  ],
  activities: [
    {
      id: "a1",
      code: "spraying-1",
      activity_type: "spraying",
      title: "Spray",
      title_ar: "رش",
      anchor: "stage",
      stage_code: "flowering",
      milestone_id: null,
      offset_days: 7,
      duration_days: 1,
      product_name: "Imidacloprid",
      dosage: "per label",
      notes: "n",
      product_name_ar: "إيميداكلوبريد",
      dosage_ar: null,
      notes_ar: "م",
      evidence_tier: "generic",
      source_tree_code: "t_hopper",
      input_id: "in-1",
      dose_value: "1.5",
      dose_value_max: null,
      dose_unit: "l_per_feddan",
      start_time: null,
      sort_order: 0,
    },
    {
      id: "a2",
      code: "harvest-1",
      activity_type: "harvest",
      title: null,
      title_ar: null,
      anchor: "milestone",
      stage_code: null,
      milestone_id: "m1",
      offset_days: 0,
      duration_days: 14,
      product_name: null,
      dosage: null,
      notes: null,
      evidence_tier: null,
      source_tree_code: null,
      start_time: null,
      sort_order: 1,
    },
  ],
} as unknown as PlanTemplateDetail;

describe("manualDraft", () => {
  it("round-trips every field, keeping codes and resolving milestone ids to codes", () => {
    const body = toWriteRequest(draftFromDetail(detail));
    expect(body.code).toBe("mango-keitt-eg");
    expect(body.name_ar).toBe("مانجو كيت");
    expect(body.milestones).toEqual([
      { code: "harvest", name: "Harvest", name_ar: null, day_from_start: 200, sort_order: 0 },
    ]);
    const [spray, harvest] = body.activities;
    expect(spray).toMatchObject({
      code: "spraying-1",
      title_ar: "رش",
      stage_code: "flowering",
      milestone_code: null,
      product_name_ar: "إيميداكلوبريد",
      notes_ar: "م",
      evidence_tier: "generic",
      source_tree_code: "t_hopper",
      input_id: "in-1",
      dose_value: 1.5,
      dose_unit: "l_per_feddan",
    });
    expect(harvest).toMatchObject({
      code: "harvest-1",
      anchor: "milestone",
      milestone_code: "harvest",
      stage_code: null,
    });
  });

  it("drops a dose without a unit and blanks empty text", () => {
    const d = emptyManual();
    d.activities = [
      { ...newActivity("flowering", 0), dose_value: 2, dose_unit: null, notes: "  " },
    ];
    const [a] = toWriteRequest(d).activities;
    expect(a.dose_value).toBeNull();
    expect(a.dose_unit).toBeNull();
    expect(a.notes).toBeNull();
    expect(a.code).toBeNull();
  });

  it("reports what blocks a save", () => {
    const d = emptyManual();
    d.activities = [{ ...newActivity(null, 0), anchor: "stage", stage_code: null }];
    expect(manualProblems(d)).toEqual([
      "editor.err.codeRequired",
      "editor.err.nameRequired",
      "editor.err.cropRequired",
      "editor.err.stageRequired",
    ]);
    expect(manualProblems(draftFromDetail(detail))).toEqual([]);
  });
});

describe("activityArabicMissing (D26)", () => {
  const legacy = { title: "Copper spray", title_ar: "رش النحاس", product_name: "Copper" };

  it("asks for Arabic on every English text of a new activity", () => {
    expect(
      activityArabicMissing({ title: "Prune", notes: "After harvest", dosage: "" }, null),
    ).toEqual(["title_ar", "notes_ar"]);
  });

  it("leaves a seeded activity's untouched English-only product alone", () => {
    expect(activityArabicMissing({ ...legacy }, legacy)).toEqual([]);
  });

  it("asks again once that product's English changes", () => {
    expect(
      activityArabicMissing({ ...legacy, product_name: "Copper oxychloride" }, legacy),
    ).toEqual(["product_name_ar"]);
  });
});
