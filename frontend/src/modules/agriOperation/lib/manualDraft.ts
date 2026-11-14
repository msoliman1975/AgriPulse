// The platform editor's working copy of an operation manual, and its
// conversion to and from the whole-tree write the API takes. Pure.
// Mirrors the old editor's load/save (PlanTemplateEditorPage) so a save here
// writes exactly what a save there did, plus nothing is dropped: every content
// field, the activity code (B3) and the input and dose (D20) round-trip.

import type {
  ActivityInput,
  ManualActivityContent,
  PlanActivityType,
  PlanTemplateDetail,
  PlanTemplateWriteRequest,
} from "@/api/planTemplates";
import { needsArabic } from "@/lib/arabicRequired";

export interface MilestoneDraft {
  key: string;
  code: string;
  name: string;
  name_ar: string;
  day_from_start: number;
}

export interface ActivityDraft extends ActivityInput {
  key: string;
}

export interface ManualDraft {
  code: string;
  name: string;
  name_ar: string;
  crop_path: string;
  country: string;
  region: string;
  description: string;
  description_ar: string;
  milestones: MilestoneDraft[];
  activities: ActivityDraft[];
}

let seq = 0;
export const nextKey = (): string => `m${(seq += 1)}`;

export function emptyManual(): ManualDraft {
  return {
    code: "",
    name: "",
    name_ar: "",
    crop_path: "",
    country: "",
    region: "",
    description: "",
    description_ar: "",
    milestones: [],
    activities: [],
  };
}

export function newActivity(stageCode: string | null, sortOrder: number): ActivityDraft {
  return {
    key: nextKey(),
    code: null,
    activity_type: "observation",
    title: null,
    title_ar: null,
    anchor: stageCode ? "stage" : "start",
    stage_code: stageCode,
    milestone_code: null,
    offset_days: 0,
    duration_days: 1,
    product_name: null,
    dosage: null,
    notes: null,
    product_name_ar: null,
    dosage_ar: null,
    notes_ar: null,
    evidence_tier: null,
    source_tree_code: null,
    input_id: null,
    dose_value: null,
    dose_value_max: null,
    dose_unit: null,
    sort_order: sortOrder,
  };
}

export function draftFromDetail(d: PlanTemplateDetail): ManualDraft {
  const msById = new Map(d.milestones.map((m) => [m.id, m.code]));
  return {
    code: d.code,
    name: d.name,
    name_ar: d.name_ar ?? "",
    crop_path: d.crop_path,
    country: d.country ?? "",
    region: d.region ?? "",
    description: d.description ?? "",
    description_ar: d.description_ar ?? "",
    milestones: d.milestones.map((m) => ({
      key: nextKey(),
      code: m.code,
      name: m.name,
      name_ar: m.name_ar ?? "",
      day_from_start: m.day_from_start,
    })),
    activities: d.activities.map((a) => ({
      key: nextKey(),
      code: a.code,
      activity_type: a.activity_type as PlanActivityType,
      title: a.title ?? null,
      title_ar: a.title_ar ?? null,
      anchor: a.anchor,
      stage_code: a.stage_code,
      milestone_code: a.milestone_id ? (msById.get(a.milestone_id) ?? null) : null,
      offset_days: a.offset_days,
      duration_days: a.duration_days,
      product_name: a.product_name,
      dosage: a.dosage,
      notes: a.notes,
      product_name_ar: a.product_name_ar ?? null,
      dosage_ar: a.dosage_ar ?? null,
      notes_ar: a.notes_ar ?? null,
      evidence_tier: a.evidence_tier ?? null,
      source_tree_code: a.source_tree_code ?? null,
      input_id: a.input_id ?? null,
      dose_value: a.dose_value == null ? null : Number(a.dose_value),
      dose_value_max: a.dose_value_max == null ? null : Number(a.dose_value_max),
      dose_unit: a.dose_unit ?? null,
      sort_order: a.sort_order,
    })),
  };
}

const text = (v: string | null | undefined): string | null => {
  const s = (v ?? "").trim();
  return s ? s : null;
};

export function toWriteRequest(d: ManualDraft): PlanTemplateWriteRequest {
  return {
    code: d.code.trim(),
    name: d.name.trim(),
    name_ar: text(d.name_ar),
    crop_path: d.crop_path.trim(),
    country: text(d.country),
    region: text(d.region),
    description: text(d.description),
    description_ar: text(d.description_ar),
    milestones: d.milestones.map((m, i) => ({
      code: m.code.trim(),
      name: m.name.trim(),
      name_ar: text(m.name_ar),
      day_from_start: Number(m.day_from_start) || 0,
      sort_order: i,
    })),
    activities: d.activities.map((a, i) => ({
      code: a.code ?? null,
      activity_type: a.activity_type,
      title: text(a.title),
      title_ar: text(a.title_ar),
      anchor: a.anchor,
      stage_code: a.anchor === "stage" ? (a.stage_code ?? null) : null,
      milestone_code: a.anchor === "milestone" ? (a.milestone_code ?? null) : null,
      offset_days: Number(a.offset_days) || 0,
      duration_days: Math.max(1, Number(a.duration_days) || 1),
      product_name: text(a.product_name),
      dosage: text(a.dosage),
      notes: text(a.notes),
      product_name_ar: text(a.product_name_ar),
      dosage_ar: text(a.dosage_ar),
      notes_ar: text(a.notes_ar),
      evidence_tier: a.evidence_tier ?? null,
      source_tree_code: text(a.source_tree_code),
      input_id: a.input_id || null,
      // A dose is saved only with a unit; the API refuses one without.
      dose_value: a.dose_unit ? (a.dose_value ?? null) : null,
      dose_value_max: a.dose_unit ? (a.dose_value_max ?? null) : null,
      dose_unit:
        a.dose_unit && (a.dose_value != null || a.dose_value_max != null) ? a.dose_unit : null,
      sort_order: i,
    })),
  };
}

/** The English/Arabic pairs on a manual activity (D26). */
export const ACTIVITY_ARABIC_PAIRS = [
  ["title", "title_ar"],
  ["notes", "notes_ar"],
  ["product_name", "product_name_ar"],
  ["dosage", "dosage_ar"],
] as const;

export type ActivityArabicField = (typeof ACTIVITY_ARABIC_PAIRS)[number][1];

type ActivityTexts = ManualActivityContent & {
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
};

/**
 * The Arabic fields this activity is missing (D26), judged as the server
 * judges it: English that is new or changed against `saved` (the stored
 * activity with the same code; null for a new one) needs Arabic, and a seeded
 * activity whose English is left alone may stay English-only.
 */
export function activityArabicMissing(
  a: ActivityTexts,
  saved: ActivityTexts | null,
): ActivityArabicField[] {
  return ACTIVITY_ARABIC_PAIRS.filter(([en, ar]) =>
    needsArabic(a[en], a[ar], saved ? { en: saved[en], ar: saved[ar] } : null),
  ).map(([, ar]) => ar);
}

/** What blocks a save, as i18n keys in the planTemplates namespace. */
export function manualProblems(d: ManualDraft): string[] {
  const out: string[] = [];
  if (!d.code.trim()) out.push("editor.err.codeRequired");
  if (!d.name.trim()) out.push("editor.err.nameRequired");
  if (!d.crop_path.trim()) out.push("editor.err.cropRequired");
  if (d.activities.some((a) => a.anchor === "milestone" && !a.milestone_code))
    out.push("editor.err.milestoneRequired");
  if (d.activities.some((a) => a.anchor === "stage" && !a.stage_code))
    out.push("editor.err.stageRequired");
  return out;
}
