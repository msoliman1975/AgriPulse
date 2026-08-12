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
  scenes: (farmId: string) => ["labs/console/scenes", farmId] as const,
  signalDefs: () => ["labs/console/signalDefs"] as const,
  signalObs: (farmId: string, defId: string | null) =>
    ["labs/console/signalObs", farmId, defId] as const,
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
