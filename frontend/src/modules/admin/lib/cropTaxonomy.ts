// Which level of the crop taxonomy a value actually comes from.
//
// Phenology and size classes are stored at three levels (crop → variety →
// strain) and resolve **deepest non-NULL wins**, replacing wholesale rather
// than merging. `default_thresholds` is the exception: it shallow-merges per
// key. Both rules are mirrored from
// backend/app/modules/farms/crop_thresholds.py — see the lock-step test.
//
// The UI needs more than the resolved value: it needs to know *where* the
// value came from, because a node that merely inherits must not be editable
// in place. Editing an inherited ladder would silently rewrite it for every
// other node inheriting the same one. So every resolver here returns the
// source level alongside the value.

import type { Crop, CropVariety, CropVarietyStrain, PhenologyStage, SizeClass } from "@/api/crops";

/** Which level supplied a resolved value. */
export type TaxonomyLevel = "crop" | "variety" | "strain";

export interface Resolved<T> {
  value: T | null;
  /** Null only when no level defines the value at all. */
  source: TaxonomyLevel | null;
}

/** The chain a value resolves along. Omit what isn't selected. */
export interface TaxonomyChain {
  crop: Crop;
  variety?: CropVariety | null;
  strain?: CropVarietyStrain | null;
}

/** The deepest level actually present in the chain — where an edit would land. */
export function deepestLevel(chain: TaxonomyChain): TaxonomyLevel {
  if (chain.strain) return "strain";
  if (chain.variety) return "variety";
  return "crop";
}

/** Dotted path of the deepest node in the chain, e.g. "mango.alphonso.a1". */
export function chainPath(chain: TaxonomyChain): string {
  if (chain.strain) return chain.strain.path;
  if (chain.variety) return chain.variety.path;
  return chain.crop.code;
}

/** Dotted path of whichever level a resolved value came from. */
export function sourcePath(chain: TaxonomyChain, source: TaxonomyLevel | null): string | null {
  if (source === "strain" && chain.strain) return chain.strain.path;
  if (source === "variety" && chain.variety) return chain.variety.path;
  if (source === "crop") return chain.crop.code;
  return null;
}

/**
 * Mirrors `resolve_phenology_stages`: strain override, else variety override,
 * else the crop's own calendar. Wholesale — never merged.
 */
export function resolvePhenology(chain: TaxonomyChain): Resolved<PhenologyStage[]> {
  const strain = chain.strain?.phenology_stages_override;
  if (strain != null) return { value: strain.stages, source: "strain" };
  const variety = chain.variety?.phenology_stages_override;
  if (variety != null) return { value: variety.stages, source: "variety" };
  const crop = chain.crop.phenology_stages;
  if (crop != null) return { value: crop.stages, source: "crop" };
  return { value: null, source: null };
}

/** Mirrors `resolve_size_classes`. Same wholesale rule as phenology. */
export function resolveSizeClasses(chain: TaxonomyChain): Resolved<SizeClass[]> {
  const strain = chain.strain?.size_classes_override;
  if (strain != null) return { value: strain.classes, source: "strain" };
  const variety = chain.variety?.size_classes_override;
  if (variety != null) return { value: variety.classes, source: "variety" };
  const crop = chain.crop.size_classes;
  if (crop != null) return { value: crop.classes, source: "crop" };
  return { value: null, source: null };
}

/**
 * Mirrors `resolve_thresholds`: shallow merge crop → variety → strain, the
 * deepest specified level winning **per key**. All-null collapses to `{}`.
 *
 * Unlike the two above, a deeper level does not have to restate the keys it
 * doesn't change — which is why this one cannot report a single source level.
 */
export function resolveThresholds(chain: TaxonomyChain): Record<string, unknown> {
  return {
    ...(chain.crop.default_thresholds ?? {}),
    ...(chain.variety?.default_thresholds ?? {}),
    ...(chain.strain?.default_thresholds ?? {}),
  };
}

/** Which level each resolved threshold key came from, for per-key provenance. */
export function thresholdSources(chain: TaxonomyChain): Record<string, TaxonomyLevel> {
  const sources: Record<string, TaxonomyLevel> = {};
  for (const key of Object.keys(chain.crop.default_thresholds ?? {})) sources[key] = "crop";
  for (const key of Object.keys(chain.variety?.default_thresholds ?? {})) sources[key] = "variety";
  for (const key of Object.keys(chain.strain?.default_thresholds ?? {})) sources[key] = "strain";
  return sources;
}

/**
 * True when the selected node defines the value itself, rather than inheriting
 * it. Only an owning node may be edited in place; anything else must first
 * take ownership via an override.
 */
export function ownsValue(chain: TaxonomyChain, source: TaxonomyLevel | null): boolean {
  return source !== null && source === deepestLevel(chain);
}
