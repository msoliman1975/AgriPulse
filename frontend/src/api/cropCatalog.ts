// Platform crop-catalog authoring API (mirrors backend /api/v1/admin/crops…).
// Codes are immutable; paths auto-derive server-side; "delete" is a soft
// retire via { is_active: false } on the update endpoints.

import { apiClient } from "./client";
import type {
  ClassificationDepth,
  Crop,
  PhenologyStage,
  CropAttributeDefinition,
  CropAttributeGate,
  CropAttributeOption,
  CropVariety,
  CropVarietyStrain,
} from "./crops";

// Crop-level agronomic settings shared by create and update.
//
// The GDD temperatures read back as strings (JSON has no decimal type) but are
// written as numbers, which is what a numeric input yields; pydantic accepts
// either. Ranges are the server's: base 0–40 °C, upper 0–60 °C.
interface CropSettingsPayload {
  is_perennial?: boolean;
  scientific_name?: string | null;
  classification_depth?: ClassificationDepth;
  default_growing_season_days?: number | null;
  /** Required before any stage may advance on `gdd_from_planting`. */
  gdd_base_temp_c?: number | null;
  gdd_upper_temp_c?: number | null;
  relevant_indices?: string[];
  /** Replaced wholesale, like the stage calendar. */
  size_classes?: { classes: SizeClassPayload[] } | null;
  /** Shallow-merged per key by the resolver — and read by nothing today. */
  default_thresholds?: Record<string, unknown> | null;
}

export interface CropCreatePayload extends CropSettingsPayload {
  code: string;
  name_en: string;
  name_ar: string;
  category: string;
}

// --- Phenology stage calendar ---------------------------------------------
//
// Mirrors backend/app/modules/farms/phenology.py. The advance rule is a
// discriminated union on `mode`, and which modes are legal depends on the
// crop: a perennial has no planting date to count from, an annual has no
// fixed calendar window. `gdd_from_planting` additionally needs the crop to
// set a GDD base temperature.

export const PERENNIAL_ADVANCE_MODES = ["calendar_doy", "manual"] as const;
export const ANNUAL_ADVANCE_MODES = ["days_from_planting", "gdd_from_planting", "manual"] as const;

export type { AdvanceRule } from "./crops";

/** What the update endpoint accepts — identical to the read shape. */
export type PhenologyStagePayload = PhenologyStage;

export interface CropUpdatePayload extends CropSettingsPayload {
  name_en?: string;
  name_ar?: string;
  category?: string;
  is_active?: boolean;
  /** The whole calendar is replaced at once — the array is too interdependent
   *  (unique codes, unique orders) to patch a stage at a time. */
  phenology_stages?: { stages: PhenologyStagePayload[] } | null;
}

// --- Size classes ----------------------------------------------------------
//
// The block canopy-size dropdown. Same shape rules as the stage calendar
// (`farms/phenology.py:SizeClasses`) minus the advance rule: unique codes,
// unique orders, both names required.

export interface SizeClassPayload {
  code: string;
  name_en: string;
  name_ar: string;
  order: number;
}

// --- Taxonomy-level overrides ----------------------------------------------
//
// Phenology and size classes resolve **deepest non-NULL wins** (strain →
// variety → crop) and are replaced *wholesale*, never merged — see
// `farms/crop_thresholds.resolve_phenology_stages`. So a variety may define a
// different number of stages than its crop, and a strain different again from
// its variety.
//
// Sending `null` clears the override, and the node inherits from its parent
// again. That is the only way back: there is no separate delete endpoint.
//
// `default_thresholds` is the odd one out — it shallow-merges per key rather
// than replacing. It is also, today, read by nothing: `resolve_thresholds()`
// has no callers anywhere in the backend.
export interface TaxonomyOverridePayload {
  phenology_stages_override?: { stages: PhenologyStagePayload[] } | null;
  size_classes_override?: { classes: SizeClassPayload[] } | null;
  default_thresholds?: Record<string, unknown> | null;
}

export interface VarietyCreatePayload extends TaxonomyOverridePayload {
  code: string;
  name_en: string;
  name_ar?: string | null;
}

export interface NodeUpdatePayload extends TaxonomyOverridePayload {
  name_en?: string;
  name_ar?: string | null;
  is_active?: boolean;
}

// ---- Crops ----------------------------------------------------------------

export async function listAdminCrops(includeInactive = false): Promise<Crop[]> {
  const { data } = await apiClient.get<Crop[]>("/v1/admin/crops", {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function createCrop(payload: CropCreatePayload): Promise<Crop> {
  const { data } = await apiClient.post<Crop>("/v1/admin/crops", payload);
  return data;
}

export async function updateCrop(cropId: string, payload: CropUpdatePayload): Promise<Crop> {
  const { data } = await apiClient.patch<Crop>(`/v1/admin/crops/${cropId}`, payload);
  return data;
}

// ---- Varieties ------------------------------------------------------------

export async function listAdminVarieties(
  cropId: string,
  includeInactive = false,
): Promise<CropVariety[]> {
  const { data } = await apiClient.get<CropVariety[]>(`/v1/admin/crops/${cropId}/varieties`, {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function createVariety(
  cropId: string,
  payload: VarietyCreatePayload,
): Promise<CropVariety> {
  const { data } = await apiClient.post<CropVariety>(
    `/v1/admin/crops/${cropId}/varieties`,
    payload,
  );
  return data;
}

export async function updateVariety(
  varietyId: string,
  payload: NodeUpdatePayload,
): Promise<CropVariety> {
  const { data } = await apiClient.patch<CropVariety>(
    `/v1/admin/crop-varieties/${varietyId}`,
    payload,
  );
  return data;
}

// ---- Strains --------------------------------------------------------------

export async function listAdminStrains(
  varietyId: string,
  includeInactive = false,
): Promise<CropVarietyStrain[]> {
  const { data } = await apiClient.get<CropVarietyStrain[]>(
    `/v1/admin/crop-varieties/${varietyId}/strains`,
    { params: { include_inactive: includeInactive } },
  );
  return data;
}

export async function createStrain(
  varietyId: string,
  payload: VarietyCreatePayload,
): Promise<CropVarietyStrain> {
  const { data } = await apiClient.post<CropVarietyStrain>(
    `/v1/admin/crop-varieties/${varietyId}/strains`,
    payload,
  );
  return data;
}

export async function updateStrain(
  strainId: string,
  payload: NodeUpdatePayload,
): Promise<CropVarietyStrain> {
  const { data } = await apiClient.patch<CropVarietyStrain>(
    `/v1/admin/crop-variety-strains/${strainId}`,
    payload,
  );
  return data;
}

// ---- Attribute definitions ------------------------------------------------
//
// The typed fields that appear on a crop → block assignment. Platform-curated
// like the rest of this file: tenants read them (via /v1/crops/…) but only a
// platform admin authors them.

export interface CropAttributeDefinitionCreate {
  /** Absent → attaches to the crop itself. A strain implies its variety. */
  crop_variety_id?: string | null;
  crop_variety_strain_id?: string | null;
  code: string;
  name_en: string;
  name_ar: string;
  description_en?: string | null;
  description_ar?: string | null;
  value_type: CropAttributeDefinition["value_type"];
  unit_en?: string | null;
  unit_ar?: string | null;
  value_min?: string | null;
  value_max?: string | null;
  decimal_places?: number | null;
  text_max_length?: number | null;
  options?: CropAttributeOption[] | null;
  is_required?: boolean;
  required_when?: CropAttributeGate | null;
  show_when?: CropAttributeGate | null;
  group_code?: string | null;
  group_name_en?: string | null;
  group_name_ar?: string | null;
  sort_order?: number;
  is_reportable?: boolean;
}

/**
 * Everything a definition can change after creation.
 *
 * `code` and the taxonomy attachment are absent on purpose — both are part of
 * the identity stored values point at, and the PATCH schema forbids extra
 * keys, so sending them back is a 422 rather than a no-op. Retiring is
 * `is_active: false`; there is no DELETE.
 */
export type CropAttributeDefinitionUpdate = Partial<
  Omit<CropAttributeDefinitionCreate, "code" | "crop_variety_id" | "crop_variety_strain_id">
> & { is_active?: boolean };

/** Every definition on a crop, at every taxonomy level. */
export async function listAdminCropAttributes(
  cropId: string,
  includeInactive = false,
): Promise<CropAttributeDefinition[]> {
  const { data } = await apiClient.get<CropAttributeDefinition[]>(
    `/v1/admin/crops/${cropId}/attribute-definitions`,
    { params: includeInactive ? { include_inactive: true } : undefined },
  );
  return data;
}

export async function createCropAttribute(
  cropId: string,
  payload: CropAttributeDefinitionCreate,
): Promise<CropAttributeDefinition> {
  const { data } = await apiClient.post<CropAttributeDefinition>(
    `/v1/admin/crops/${cropId}/attribute-definitions`,
    payload,
  );
  return data;
}

export async function updateCropAttribute(
  definitionId: string,
  payload: CropAttributeDefinitionUpdate,
): Promise<CropAttributeDefinition> {
  const { data } = await apiClient.patch<CropAttributeDefinition>(
    `/v1/admin/crop-attribute-definitions/${definitionId}`,
    payload,
  );
  return data;
}
