import { QueryClient } from "@tanstack/react-query";

/**
 * Singleton TanStack Query client. Mounted once at the root via
 * `QueryClientProvider` so caches survive route changes within a session.
 *
 * Defaults:
 *   - staleTime 30 s — most reads are dashboard-style, this avoids
 *     re-querying on every render but stays fresh enough that an
 *     operator's PATCH lands quickly.
 *   - retry: 1 — surfaces network errors fast; the axios interceptor
 *     handles 401s separately, so retrying them is wasted work.
 *   - refetchOnWindowFocus: false — the app is heavy enough that
 *     incidental focus events shouldn't trigger storms; explicit
 *     refetches happen on user action or interval.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
