// Non-component constants for the Farm Console, kept out of the component
// files so react-refresh (fast refresh) stays happy.
import type { Health, IndexCode } from "../map/types";

// Mirror the map's health palette so the rail dot, the inspector badge and
// the polygon fill all agree at a glance.
export const HEALTH_DOT: Record<Health, string> = {
  healthy: "#4f8e4a",
  watch: "#c98a18",
  critical: "#b24430",
  unknown: "#9c9c9c",
};

// The three block-level indices the backend actually serves. NDMI/EVI/etc.
// exist only at sub-block grid resolution, so we present the real three —
// one per agronomic "family" — to avoid implying data we don't have.
export const INDEX_ORDER: IndexCode[] = ["ndvi", "ndre", "ndwi"];
export const INDEX_META: Record<IndexCode, { label: string; family: string; meaning: string }> = {
  ndvi: { label: "NDVI", family: "Vigour & canopy", meaning: "Overall canopy vigour" },
  ndre: { label: "NDRE", family: "Nutrition", meaning: "Canopy nitrogen (red-edge)" },
  ndwi: { label: "NDWI", family: "Water & moisture", meaning: "Canopy water content" },
};
