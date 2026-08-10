import { apiClient } from "./client";

// Exact depth a block assignment for this crop must specify.
export type ClassificationDepth = "crop_only" | "variety" | "variety_strain";

export interface Crop {
  id: string;
  code: string;
  name_en: string;
  name_ar: string;
  scientific_name: string | null;
  category: string;
  is_perennial: boolean;
  default_growing_season_days: number | null;
  relevant_indices: string[];
  classification_depth: ClassificationDepth;
  is_active: boolean;
  /** Base temperature for growing-degree-day accumulation. A stage that
   *  advances on GDD is only valid when the crop sets this. */
  gdd_base_temp_c?: string | null;
  /** Upper cutoff for GDD accumulation. Optional even when a base is set. */
  gdd_upper_temp_c?: string | null;
  /** The crop's stage calendar. Null for most crops today — a block whose crop
   *  has none can never advance a growth stage on its own. */
  phenology_stages?: { stages: PhenologyStage[] } | null;
  /** Canopy size classes offered on a block assignment. */
  size_classes?: { classes: SizeClass[] } | null;
  /** Opaque per-key JSON, shallow-merged down the taxonomy. Nothing reads it
   *  yet — `resolve_thresholds()` has no callers. */
  default_thresholds?: Record<string, unknown> | null;
}

/** One canopy size class. Mirrors `farms/phenology.py:SizeClass`. */
export interface SizeClass {
  code: string;
  name_en: string;
  name_ar: string;
  order: number;
}

/**
 * Phenology and size classes a variety or strain defines *instead of* the
 * level above it — never merged with it. `null` (or absent) means the node
 * inherits, and the nearest ancestor with a non-null value wins: a strain
 * falls back to its variety, not straight to the crop.
 */
export interface TaxonomyOverrides {
  phenology_stages_override?: { stages: PhenologyStage[] } | null;
  size_classes_override?: { classes: SizeClass[] } | null;
  default_thresholds?: Record<string, unknown> | null;
}

export interface CropVariety extends TaxonomyOverrides {
  id: string;
  crop_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  // Canonical hierarchical code "<crop>.<variety>".
  path: string;
  is_active: boolean;
}

export interface CropVarietyStrain extends TaxonomyOverrides {
  id: string;
  crop_variety_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  // Canonical hierarchical code "<crop>.<variety>.<strain>".
  path: string;
  is_active: boolean;
}

export type CropAttributeValueType =
  | "integer"
  | "decimal"
  | "text"
  | "boolean"
  | "date"
  | "single_select"
  | "multi_select";

export interface CropAttributeOption {
  code: string;
  name_en: string;
  name_ar: string;
  sort_order: number;
}

/** A one-level gate: `{code, in: [...]}` or `{code, eq: ...}`. */
export interface CropAttributeGate {
  code: string;
  in?: (string | boolean)[];
  eq?: string | boolean;
}

/** Platform-curated typed field on the crop → block assignment.
 *
 *  Unlike every other decision-tree condition source, the set of these is
 *  data rather than a frontend constant — it comes from the crop catalog and
 *  grows with it. That is why the condition builder fetches this list instead
 *  of holding a hardcoded array like INDEX_CODES or WEATHER_RISK_CODES. */
export interface CropAttributeDefinition {
  id: string;
  crop_id: string;
  crop_variety_id: string | null;
  crop_variety_strain_id: string | null;
  // Taxonomy node the definition attaches to ("mango", "mango.sukkary", …).
  path: string;
  code: string;
  name_en: string;
  name_ar: string;
  description_en: string | null;
  description_ar: string | null;
  value_type: CropAttributeValueType;
  unit_en: string | null;
  unit_ar: string | null;
  value_min: string | null;
  value_max: string | null;
  decimal_places: number | null;
  text_max_length: number | null;
  options: CropAttributeOption[] | null;
  is_required: boolean;
  required_when: CropAttributeGate | null;
  show_when: CropAttributeGate | null;
  group_code: string | null;
  group_name_en: string | null;
  group_name_ar: string | null;
  sort_order: number;
  is_reportable: boolean;
  is_active: boolean;
}

export interface ResolvedCropAttributes {
  crop_path: string;
  definitions: CropAttributeDefinition[];
  // Inherited codes a deeper level replaced — shown in the authoring UI so an
  // edit that appears to do nothing is explicable.
  shadowed_codes: string[];
}

/** Flat catalog across every crop — the decision-tree condition builder. */
export async function listCropAttributeCatalog(): Promise<CropAttributeDefinition[]> {
  const { data } = await apiClient.get<CropAttributeDefinition[]>(
    "/v1/crops/attribute-definitions",
  );
  return data;
}

/** Deepest-wins definitions for one crop path — the assignment form. */
export async function resolveCropAttributes(cropPath: string): Promise<ResolvedCropAttributes> {
  const { data } = await apiClient.get<ResolvedCropAttributes>("/v1/crops/resolved-attributes", {
    params: { crop_path: cropPath },
  });
  return data;
}

export async function listCrops(category?: string): Promise<Crop[]> {
  const { data } = await apiClient.get<Crop[]>("/v1/crops", {
    params: category ? { category } : undefined,
  });
  return data;
}

export async function listCropVarieties(cropId: string): Promise<CropVariety[]> {
  const { data } = await apiClient.get<CropVariety[]>(`/v1/crops/${cropId}/varieties`);
  return data;
}

export async function listVarietyStrains(cropVarietyId: string): Promise<CropVarietyStrain[]> {
  const { data } = await apiClient.get<CropVarietyStrain[]>(
    `/v1/crop-varieties/${cropVarietyId}/strains`,
  );
  return data;
}

// --- Resolved taxonomy (phenology stages + size classes) ------------------

/** How a stage decides it is the current one. Discriminated on `mode`;
 *  mirrors the Advance union in backend/app/modules/farms/phenology.py. */
export type AdvanceRule =
  | { mode: "manual" }
  | { mode: "calendar_doy"; start_doy: string; end_doy: string }
  | { mode: "days_from_planting"; start_day: number; end_day: number }
  | { mode: "gdd_from_planting"; start_gdd: number; end_gdd: number };

export interface PhenologyStage {
  code: string;
  name_en: string;
  name_ar: string;
  order: number;
  advance: AdvanceRule;
}

export interface ResolvedTaxonomy {
  crop_path: string;
  phenology_stages: { stages: PhenologyStage[] } | null;
  size_classes: { classes?: { code: string }[] } | null;
}

/** Deepest-wins resolution for a crop path: a variety's own stage calendar
 *  overrides the crop's. `phenology_stages` is null when no level of the
 *  taxonomy defines one — which is most crops today, and is why the stage
 *  control has an explicit empty state. */
export async function getResolvedTaxonomy(cropPath: string): Promise<ResolvedTaxonomy> {
  const { data } = await apiClient.get<ResolvedTaxonomy>("/v1/crops/resolved-taxonomy", {
    params: { crop_path: cropPath },
  });
  return data;
}
