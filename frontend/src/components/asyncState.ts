import { useCallback, useEffect, useState, type DependencyList } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { isApiError } from "@/api/errors";

/**
 * The neutral async shape every data surface renders from.
 *
 * Deliberately NOT `UseQueryResult`. Three reasons:
 *
 *  1. 18 pages still fetch with `useEffect` + `useState`. Taking a query
 *     result would make the react-query migration a hard prerequisite for
 *     adopting the layout templates; with this shape a page can convert its
 *     layout first and its data layer later (or in the same PR — but by
 *     choice, not by force).
 *  2. `<AsyncBoundary>` and `<DataTable>` stay unit-testable without
 *     standing up a `QueryClientProvider`.
 *  3. `filtered` — needed to tell "nothing exists yet" from "nothing matches
 *     your search" — is knowledge only the page has. It can't come from a
 *     query result, and getting it wrong is why most pages currently tell a
 *     user who mistyped a search that the system holds no data.
 */
export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: unknown; retry?: () => void }
  | { status: "success"; data: T };

/** What a consumer should actually render. Resolved once, used by both
 *  <AsyncBoundary> and <DataTable> so the ladder can't drift between them. */
export type AsyncSlot<T> =
  | { kind: "loading" }
  | { kind: "error"; error: unknown; retry?: () => void }
  | { kind: "empty" }
  | { kind: "noResults" }
  | { kind: "data"; data: T };

function defaultIsEmpty<T>(data: T): boolean {
  if (Array.isArray(data)) return data.length === 0;
  return data === null || data === undefined;
}

export function resolveAsyncSlot<T>(
  state: AsyncState<T>,
  options: { isEmpty?: (data: T) => boolean; filtered?: boolean } = {},
): AsyncSlot<T> {
  if (state.status === "loading") return { kind: "loading" };
  if (state.status === "error") {
    return { kind: "error", error: state.error, retry: state.retry };
  }
  const isEmpty = options.isEmpty ?? defaultIsEmpty;
  if (isEmpty(state.data)) {
    return options.filtered ? { kind: "noResults" } : { kind: "empty" };
  }
  return { kind: "data", data: state.data };
}

/**
 * Project the success payload without disturbing loading/error.
 *
 * List endpoints return an envelope (`{ items, total, … }`) while
 * `<DataTable>`/`<RowList>` want the rows, so this conversion happens on every
 * index page.
 */
export function mapAsyncState<A, B>(state: AsyncState<A>, fn: (data: A) => B): AsyncState<B> {
  return state.status === "success" ? { status: "success", data: fn(state.data) } : state;
}

/** Adapter for react-query. */
export function queryState<T>(query: UseQueryResult<T>): AsyncState<T> {
  if (query.isError) {
    return { status: "error", error: query.error, retry: () => void query.refetch() };
  }
  // `isPending` covers the first load; `data === undefined` covers a disabled
  // or reset query that hasn't produced anything yet. Either way there is
  // nothing to render but a skeleton.
  if (query.isPending || query.data === undefined) {
    return { status: "loading" };
  }
  return { status: "success", data: query.data };
}

/**
 * Adapter for pages still on `useEffect` + `useState`. Handles the
 * cancelled-on-unmount guard those pages all hand-roll, and wires a retry.
 *
 * This is a migration aid, not a react-query replacement — new code should
 * use a query hook from `@/queries/*`.
 */
export function useAsyncData<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fn()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", error, retry });
      });
    return () => {
      cancelled = true;
    };
    // `deps` is the caller's dependency list, spread so this hook behaves like
    // the `useEffect` it replaces. The linter can't statically verify a
    // pass-through list; `fn` is intentionally excluded because callers pass an
    // inline closure that would re-fire on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt, retry]);

  return state;
}

/** Turn any thrown value into something worth showing a user. */
export function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isApiError(error)) return error.problem.detail ?? error.problem.title;
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  return fallback;
}
