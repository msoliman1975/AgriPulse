/** Inputs catalogue (decision D20). Platform rows plus the caller's own tenant rows. */

import { apiClient } from "./client";

export const INPUT_CATEGORIES = [
  "organic_fertiliser",
  "biological_agent",
  "mineral_or_botanical_treatment",
  "foliar_nutrient",
  "growth_regulator",
  "trap_or_bait",
  "bag_or_cover",
] as const;
export type InputCategory = (typeof INPUT_CATEGORIES)[number];

export const INPUT_METHODS = [
  "basin",
  "spray",
  "dust",
  "release",
  "trap",
  "injection",
  "cover",
  "foliar",
  "soil_mix",
] as const;
export type InputMethod = (typeof INPUT_METHODS)[number];

export const ORGANIC_STATUSES = ["permitted", "restricted", "not_permitted", "unverified"] as const;
export type OrganicStatus = (typeof ORGANIC_STATUSES)[number];

export const DOSE_UNITS = [
  "kg/plant",
  "g/plant",
  "L/plant/week",
  "cards/plant",
  "kg/plant/year_of_age",
  "g/100 L",
  "mg/L",
  "%",
  "ppm",
  "traps/ha",
  "kg/ha",
  "L/ha",
  "other",
] as const;
export type DoseUnit = (typeof DOSE_UNITS)[number];

type Num = string | number | null;

export interface InputDose {
  crop_path: string | null;
  value: Num;
  value_min: Num;
  value_max: Num;
  unit: DoseUnit;
  unit_note: string | null;
  context: string | null;
  reference: string | null;
}

export interface Input {
  id: string;
  scope: "platform" | "tenant";
  code: string;
  name_en: string;
  name_ar: string | null;
  category: InputCategory;
  active_ingredient: string | null;
  methods: InputMethod[];
  organic_status: OrganicStatus;
  organic_list: string | null;
  phi_days: number | null;
  rei_hours: number | null;
  crop_paths: string[];
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  doses: InputDose[];
}

export interface InputFields {
  name_en?: string;
  name_ar?: string | null;
  category?: InputCategory;
  active_ingredient?: string | null;
  methods?: InputMethod[];
  organic_status?: OrganicStatus;
  organic_list?: string | null;
  phi_days?: number | null;
  rei_hours?: number | null;
  crop_paths?: string[];
  notes?: string | null;
  is_active?: boolean;
}

export async function listInputs(params: {
  cropPath?: string;
  category?: InputCategory | "";
  q?: string;
  includeInactive?: boolean;
}): Promise<Input[]> {
  const { data } = await apiClient.get<Input[]>("/v1/inputs", {
    params: {
      crop_path: params.cropPath || undefined,
      category: params.category || undefined,
      q: params.q || undefined,
      include_inactive: params.includeInactive || undefined,
    },
  });
  return Array.isArray(data) ? data.map((i) => ({ ...i, doses: i.doses ?? [] })) : [];
}

export async function createInput(
  fields: InputFields & { code: string; name_en: string; category: InputCategory },
): Promise<Input> {
  const { data } = await apiClient.post<Input>("/v1/inputs", fields);
  return data;
}

export async function updateInput(id: string, fields: InputFields): Promise<Input> {
  const { data } = await apiClient.patch<Input>(`/v1/inputs/${id}`, fields);
  return data;
}

export async function replaceInputDoses(id: string, doses: InputDose[]): Promise<Input> {
  const { data } = await apiClient.put<Input>(`/v1/inputs/${id}/doses`, { doses });
  return data;
}

const n = (x: Num): string => (x === null || x === undefined ? "" : String(Number(x)));

/** "100–150 g/plant", "50 kg/plant", "0.75 %". */
export function formatDose(d: InputDose): string {
  const range =
    d.value_min !== null || d.value_max !== null
      ? `${n(d.value_min) || "…"}–${n(d.value_max) || "…"}`
      : "";
  const amount = d.value !== null ? (range ? `${n(d.value)} (${range})` : n(d.value)) : range;
  const unit = d.unit === "other" ? (d.unit_note ?? "") : d.unit;
  return `${amount} ${unit}`.trim();
}
