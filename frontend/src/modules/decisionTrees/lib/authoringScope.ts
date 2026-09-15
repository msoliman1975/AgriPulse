import { listCountries, listCountriesAdmin, type Country } from "@/api/countries";
import {
  listCropAttributeCatalog,
  listPlatformCropAttributeCatalog,
  type CropAttributeDefinition,
} from "@/api/crops";
import {
  getPlatformWeatherIndexCatalog,
  getWeatherIndexCatalog,
  type WeatherIndexCatalogItem,
} from "@/api/weatherIndices";
import {
  listPlatformSignalDefinitions,
  listSignalDefinitions,
  type SignalDefinition,
} from "@/api/signals";
import { useClaims } from "@/rbac/useCapability";

/**
 * Which catalogue the signed-in caller authors.
 *
 * The backend has two authoring scopes and this mirrors them exactly. A
 * tenant-scoped caller authors rows with their own `tenant_id`; a caller with
 * a platform role and no tenant authors rows with `tenant_id IS NULL`, the
 * platform catalogue. Nobody authors both, and neither can edit the other's
 * rows — the API refuses it either way.
 *
 * See `_ensure_authoring_scope` in the recommendations router.
 */
export type AuthoringScope = "platform" | "tenant";

export function useAuthoringScope(): AuthoringScope {
  const claims = useClaims();
  return claims?.tenant_id ? "tenant" : "platform";
}

/**
 * Whether this scope may edit this tree.
 *
 * A platform tree is `tenant_id === null`. The list page has always hidden its
 * own row actions on this rule; the viewer learned it in #665. Getting it
 * wrong offers a Save that the API refuses, and the refusal reads as "no such
 * tree" about a tree the author has open on screen.
 */
export function isEditableInScope(
  scope: AuthoringScope,
  tree: { tenant_id: string | null },
): boolean {
  return scope === "platform" ? tree.tenant_id === null : tree.tenant_id !== null;
}

/** The route prefix the two scopes live under. */
export function treesBasePath(scope: AuthoringScope): string {
  return scope === "platform" ? "/platform/decision-trees" : "/decision-trees";
}

/**
 * The country list, from whichever route this caller may read.
 *
 * `/v1/countries` asserts a tenant context, so a platform admin gets 403 and
 * the picker offers nothing — which is the one thing the picker exists for.
 * `/v1/admin/countries` is the same catalogue behind `platform.read`.
 */
export function countriesForScope(scope: AuthoringScope): Promise<Country[]> {
  return scope === "platform" ? listCountriesAdmin() : listCountries();
}

/**
 * Signal definitions, from whichever route this caller may read.
 *
 * `/v1/signals/definitions` is tenant-scoped, so a platform admin got 403 and
 * the condition editor's signal picker came back empty — a `{source: signals}`
 * predicate could be read but not authored.
 */
export function signalDefinitionsForScope(scope: AuthoringScope): Promise<SignalDefinition[]> {
  return scope === "platform" ? listPlatformSignalDefinitions() : listSignalDefinitions();
}

/**
 * Crop attribute definitions, from whichever route this caller may read.
 *
 * `/v1/crops/attribute-definitions` is tenant-scoped, so a platform admin got
 * 403 and the condition editor's crop-attribute codes came back empty. This is
 * the one condition source whose vocabulary is data rather than a constant in
 * the frontend, so an empty list is the whole picker.
 */
export function cropAttributeCatalogForScope(
  scope: AuthoringScope,
): Promise<CropAttributeDefinition[]> {
  return scope === "platform" ? listPlatformCropAttributeCatalog() : listCropAttributeCatalog();
}

/**
 * The weather-index catalog, from whichever route this caller may read.
 *
 * `/v1/weather/indices/catalog` is tenant-scoped, so a platform admin got 403
 * and the weather-index picker rendered with no bilingual descriptions.
 */
export function weatherIndexCatalogForScope(
  scope: AuthoringScope,
): Promise<WeatherIndexCatalogItem[]> {
  return scope === "platform" ? getPlatformWeatherIndexCatalog() : getWeatherIndexCatalog();
}
