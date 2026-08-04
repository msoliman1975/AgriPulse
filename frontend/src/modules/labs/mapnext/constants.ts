// Non-component constants for the Farm Console, kept out of the component
// files so react-refresh (fast refresh) stays happy.
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { Health, IndexCode } from "../map/types";

// Last farm the user looked at, so /labs/map with no :farmId can restore it.
// Shared by the console and the create-farm flow (which writes it on success).
export const LAST_FARM_KEY = "labs/map/lastFarm";

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
// see BLOCK_LEVEL_INDICES — so only those can be charted for a whole block.
export const MAP_INDEX_ORDER: ApiIndexCode[] = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi", "ndmi"];
export const BLOCK_LEVEL_INDICES: IndexCode[] = ["ndvi", "ndre", "ndwi"];

export function isBlockLevel(c: ApiIndexCode): c is IndexCode {
  return c === "ndvi" || c === "ndre" || c === "ndwi";
}

// ---- agronomic families ---------------------------------------------------
//
// Indices grouped by the question they answer rather than by acronym: is the
// canopy growing, is it fed, is it thirsty. The Farm Console's first inspector
// filed them this way and printed the family as a heading above each index
// (#228); the grouping was dropped when the four grid-only indices arrived and
// broke the one-index-per-family symmetry (#234), leaving a flat grid and then
// a flat pill row. The dock restores it as one tab per family.
export type IndexFamilyKey = "vigour" | "nutrition" | "moisture";

export const INDEX_FAMILIES: { key: IndexFamilyKey; indices: ApiIndexCode[] }[] = [
  { key: "vigour", indices: ["ndvi", "evi", "savi"] },
  { key: "nutrition", indices: ["ndre", "gndvi"] },
  { key: "moisture", indices: ["ndwi", "ndmi"] },
];

// The one block-level index in each family — what that family's tab charts,
// since the grid-only members have no block-wide series to plot.
export const FAMILY_PRIMARY: Record<IndexFamilyKey, IndexCode> = {
  vigour: "ndvi",
  nutrition: "ndre",
  moisture: "ndwi",
};

// Family names and one-line meanings are i18n keys (`dock.family.*`,
// `dock.meaning.*`), not English literals in this table: they are read as tab
// labels now, and an English tab in the Arabic nav is a worse failure than the
// untranslated tooltip they used to be.
export const INDEX_META: Record<ApiIndexCode, { label: string; family: IndexFamilyKey }> = {
  ndvi: { label: "NDVI", family: "vigour" },
  evi: { label: "EVI", family: "vigour" },
  savi: { label: "SAVI", family: "vigour" },
  ndre: { label: "NDRE", family: "nutrition" },
  gndvi: { label: "GNDVI", family: "nutrition" },
  ndwi: { label: "NDWI", family: "moisture" },
  ndmi: { label: "NDMI", family: "moisture" },
};
