import { apiClient } from "./client";

// Platform-curated country catalog. Used to target Decision Trees by country
// and to set a farm's location. Code is ISO 3166-1 alpha-2 (immutable).
export interface Country {
  id: string;
  code: string;
  name_en: string;
  name_ar: string;
  is_active: boolean;
}

export interface CountryCreate {
  code: string;
  name_en: string;
  name_ar: string;
}

export interface CountryUpdate {
  name_en?: string;
  name_ar?: string;
  is_active?: boolean;
}

// Tenant read — active countries only.
export async function listCountries(): Promise<Country[]> {
  const { data } = await apiClient.get<Country[]>("/v1/countries");
  return data;
}

// Platform admin — optionally include retired rows.
export async function listCountriesAdmin(includeInactive = false): Promise<Country[]> {
  const { data } = await apiClient.get<Country[]>("/v1/admin/countries", {
    params: includeInactive ? { include_inactive: true } : undefined,
  });
  return data;
}

export async function createCountry(payload: CountryCreate): Promise<Country> {
  const { data } = await apiClient.post<Country>("/v1/admin/countries", payload);
  return data;
}

export async function updateCountry(
  countryId: string,
  payload: CountryUpdate,
): Promise<Country> {
  const { data } = await apiClient.patch<Country>(`/v1/admin/countries/${countryId}`, payload);
  return data;
}
