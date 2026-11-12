// D21 crop scope of a signal or scout form, seen from one crop path.
//
// A row with no crop paths applies to every crop. A scoped row applies to a
// path when one of its scopes is that path or a crop above it, which is the
// rule the backend snapshot uses to switch a signal on for a block. A scope
// below the path (a variety's signal, seen from the crop) does not apply.
// Keep identical to `_APPLIES_TO_BLOCK_SQL` in backend signals/snapshot.py.

export type ScopeAtPath =
  /** Scoped to exactly this path: removable here. */
  | "here"
  /** Scoped to a crop above this path; managed there. */
  | "inherited"
  /** Unscoped: applies to every crop. */
  | "all"
  /** Does not apply to this path. */
  | "none";

export function scopeAtPath(cropPaths: readonly string[], path: string): ScopeAtPath {
  if (cropPaths.length === 0) return "all";
  if (cropPaths.includes(path)) return "here";
  if (cropPaths.some((p) => path.startsWith(`${p}.`))) return "inherited";
  return "none";
}

/** The crop paths after scoping a row to `path` too. Sorted, no duplicates,
 *  matching how the backend stores them. */
export function withPath(cropPaths: readonly string[], path: string): string[] {
  return [...new Set([...cropPaths, path])].sort();
}

/** The crop paths after unscoping `path`. Empty means every crop, so the
 *  caller must warn before removing the last one. */
export function withoutPath(cropPaths: readonly string[], path: string): string[] {
  return cropPaths.filter((p) => p !== path);
}
