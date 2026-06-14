// Non-component constants for the Farm Console, kept out of the component
// files so react-refresh (fast refresh) stays happy.
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { Health, IndexCode } from "../map/types";

// Mirror the map's health palette so the rail dot, the inspector badge and
// the polygon fill all agree at a glance.
export const HEALTH_DOT: Record<Health, string> = {
  healthy: "#4f8e4a",
  watch: "#c98a18",
  critical: "#b24430",
  unknown: "#9c9c9c",
};

// The full index set the sub-block grid pipeline supports (what the map can
// colour by). The block-level time-series API only serves three of these —
// see BLOCK_LEVEL_INDICES — so the inspector only charts those.
export const MAP_INDEX_ORDER: ApiIndexCode[] = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi", "ndmi"];
export const BLOCK_LEVEL_INDICES: IndexCode[] = ["ndvi", "ndre", "ndwi"];

export function isBlockLevel(c: ApiIndexCode): c is IndexCode {
  return c === "ndvi" || c === "ndre" || c === "ndwi";
}

export const INDEX_META: Record<ApiIndexCode, { label: string; family: string; meaning: string }> = {
  ndvi: { label: "NDVI", family: "Vigour & canopy", meaning: "Overall canopy vigour" },
  evi: { label: "EVI", family: "Vigour & canopy", meaning: "Vigour, less soil & haze noise" },
  savi: { label: "SAVI", family: "Vigour & canopy", meaning: "Vigour adjusted for bare soil" },
  ndre: { label: "NDRE", family: "Nutrition", meaning: "Canopy nitrogen (red-edge)" },
  gndvi: { label: "GNDVI", family: "Nutrition", meaning: "Chlorophyll / greenness" },
  ndwi: { label: "NDWI", family: "Water & moisture", meaning: "Canopy water content" },
  ndmi: { label: "NDMI", family: "Water & moisture", meaning: "Vegetation moisture (SWIR)" },
};
