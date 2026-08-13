/**
 * The server's answer to "what does each of my roles actually grant?".
 *
 * `capabilities.ts` is a compiled-in mirror of the backend YAML. That was
 * merely fragile while the matrix was static; now that a Platform Admin can
 * edit it at runtime it is **wrong by construction** — a toggle would take
 * effect in the API immediately while every browser kept rendering the old
 * affordances until the next deploy.
 *
 * So `/v1/me` carries the effective grants and this module holds them.
 *
 * Deliberately a module-level store rather than react-query state, read
 * through `useSyncExternalStore`. `useCapability` is called from ~40
 * components including route guards; making it a `useQuery` consumer would
 * require a `QueryClientProvider` above every one of them, which is a large
 * and pointless change to the test tree for data that is fetched once per
 * session. Nothing here fetches — `fetchMe` publishes, this stores.
 *
 * Empty until the first `/v1/me` response, and the resolver falls back to the
 * bundled mirror while it is. That keeps first paint working and matches
 * today's behaviour exactly, which is why this change is invisible until an
 * override actually exists.
 */

/** role name -> capabilities it grants, or the literal `["*"]` for a wildcard. */
export type EffectiveGrants = Record<string, string[]>;

let grants: EffectiveGrants | null = null;
const listeners = new Set<() => void>();

/** Called from `fetchMe`. Replaces the whole map — it is always a full answer. */
export function setEffectiveGrants(next: EffectiveGrants | null | undefined): void {
  // Referential identity is the store's change signal, so only swap when the
  // content actually differs. /v1/me refetches on window focus; re-publishing
  // an identical map would re-render every capability-gated component in the
  // tree for nothing.
  if (sameGrants(grants, next)) return;
  grants = next ?? null;
  for (const listener of listeners) listener();
}

/**
 * The current map, or `null` when `/v1/me` has not answered yet — callers
 * must treat `null` as "fall back to the bundled mirror", not as "no grants".
 */
export function getEffectiveGrants(): EffectiveGrants | null {
  return grants;
}

export function subscribeToEffectiveGrants(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Test hook — drop the published grants so the bundled fallback applies. */
export function resetEffectiveGrants(): void {
  grants = null;
  for (const listener of listeners) listener();
}

function sameGrants(a: EffectiveGrants | null, b: EffectiveGrants | null | undefined): boolean {
  if (a === (b ?? null)) return true;
  if (!a || !b) return false;
  const roles = Object.keys(a);
  if (roles.length !== Object.keys(b).length) return false;
  return roles.every((role) => {
    const left = a[role];
    const right = b[role];
    return (
      right !== undefined &&
      left.length === right.length &&
      left.every((cap, i) => cap === right[i])
    );
  });
}
