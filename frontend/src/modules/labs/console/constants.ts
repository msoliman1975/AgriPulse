// Non-component constants for Farm Console v2.
//
// The query keys live here rather than inline so v2 can never collide with
// the live console's `labs/mapnext/*` namespace. That separation is not
// cosmetic: v2 adds a scene-date dimension to the grid and detail queries,
// and a shared key namespace would mean a v2 parameter change could serve
// the live console stale or wrong-date cells out of a warm cache.
export const CONSOLE_QK = {
  farmsList: () => ["labs/console/farmsList"] as const,
  summary: (farmId: string) => ["labs/console/summary", farmId] as const,
  detail: (farmId: string, unitId: string | null, lang: string) =>
    ["labs/console/detail", farmId, unitId, lang] as const,
  blockHealth: (farmId: string) => ["labs/console/blockHealth", farmId] as const,
  subs: (blockId: string | null) => ["labs/console/subs", blockId] as const,
  // `at` is part of the key, not just the fetcher: the same farm and index at
  // two scenes are two different results, and a key that omitted it would
  // serve whichever scene happened to be cached first.
  farmGrid: (farmId: string, index: string, overlayKey: string, at: string | null) =>
    ["labs/console/farmGrid", farmId, index, overlayKey, at] as const,
  // The index is in the key because it is in the REQUEST: the timeline is
  // scoped to the products that produce it, and a Sentinel-2 farm and a
  // Landsat one have different acquisition days. A key that omitted it would
  // paint the optical strip over a thermal reading, and the dates on it would
  // resolve to passes with no thermal raster behind them.
  scenes: (farmId: string, index: string) => ["labs/console/scenes", farmId, index] as const,
  // Which raster each block draws for a pass. Keyed on `at` for the same
  // reason farmGrid is: the same farm at two scenes is two different answers —
  // and on the index, which decides which product's raster is returned at all.
  sceneAssets: (farmId: string, at: string | null, index: string) =>
    ["labs/console/sceneAssets", farmId, at, index] as const,
  // Pixel statistics per class. `assetCount` is in the key so the query
  // re-runs when a block's raster appears or disappears — the asset list is
  // the query's real input, and a stable key would serve a stale farm-wide
  // total after a scene change added a block.
  pixelStats: (farmId: string, index: string, at: string | null, assetCount: number) =>
    ["labs/console/pixelStats", farmId, index, at, assetCount] as const,
  signalDefs: () => ["labs/console/signalDefs"] as const,
  // Not keyed on the signal definition: the console fetches the farm's whole
  // observation set once and filters client-side, so keying on the picker
  // would split one cache entry into one per signal type.
  signalObs: (farmId: string) => ["labs/console/signalObs", farmId] as const,
  farm: (farmId: string) => ["labs/console/farm", farmId] as const,
  block: (blockId: string) => ["labs/console/block", blockId] as const,
  inactivatePreview: (blockId: string | null) =>
    ["labs/console/inactivatePreview", blockId] as const,
  farmInactivatePreview: (farmId: string) =>
    ["labs/console/farmInactivatePreview", farmId] as const,
} as const;

/** Every query this module owns, for a blanket invalidate after a write. */
export const CONSOLE_QK_ROOT = "labs/console/";

/**
 * True for any query key this module owns. A react-query key is
 * `readonly unknown[]`, so the first element has to be narrowed rather than
 * stringified — `String(unknown)` would happily render an object as
 * "[object Object]" and silently match nothing.
 */
export function isConsoleQueryKey(key: readonly unknown[]): boolean {
  const head = key[0];
  return typeof head === "string" && head.startsWith(CONSOLE_QK_ROOT);
}
