import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "./Button";
import { ErrorState } from "./ErrorState";
import { Skeleton } from "./Skeleton";
import { resolveAsyncSlot, resolveErrorMessage, type AsyncState } from "./asyncState";

interface AsyncBoundaryProps<T> {
  state: AsyncState<T>;
  /** `"block"` for a single placeholder panel, `"lines"` for stacked row
   *  placeholders. Tables use `<DataTable state>` instead, which keeps its
   *  header mounted while the rows load (decision 3B). */
  skeleton?: "block" | "lines";
  /** Bring your own placeholder; takes precedence over `skeleton`. */
  skeletonNode?: ReactNode;
  skeletonLines?: number;
  skeletonClassName?: string;
  /** Defaults to "empty array / null-ish". */
  isEmpty?: (data: T) => boolean;
  /** True when a search or filter is narrowing the result. Selects
   *  `noResults` over `empty` — these are different states and need
   *  different words. */
  filtered?: boolean;
  /** Required: an empty screen is an invitation to act, so it must offer
   *  one. `<EmptyState>` takes an `action` slot for exactly this (F-8). */
  empty: ReactNode;
  /** Falls back to `empty` when a page has no filters. */
  noResults?: ReactNode;
  children: (data: T) => ReactNode;
}

/*
 * The one loading -> error -> empty -> no-results -> data ladder.
 *
 * ~18 pages hand-wrote this, each subtly differently, and 145 inline
 * `text-ap-crit` strings served as the error branch (losing `role="alert"`
 * every time). Centralising it also makes the empty/no-results distinction
 * automatic rather than a thing each author has to remember.
 */
export function AsyncBoundary<T>({
  state,
  skeleton = "block",
  skeletonNode,
  skeletonLines = 3,
  skeletonClassName,
  isEmpty,
  filtered,
  empty,
  noResults,
  children,
}: AsyncBoundaryProps<T>): ReactNode {
  const { t } = useTranslation("common");
  const slot = resolveAsyncSlot(state, { isEmpty, filtered });

  switch (slot.kind) {
    case "loading":
      if (skeletonNode) return <>{skeletonNode}</>;
      if (skeleton === "lines") {
        return (
          <div className="flex flex-col gap-2">
            {Array.from({ length: skeletonLines }, (_, i) => (
              <Skeleton key={i} className={skeletonClassName ?? "h-16 w-full rounded-xl"} />
            ))}
          </div>
        );
      }
      return <Skeleton className={skeletonClassName ?? "h-40 w-full rounded-xl"} />;

    case "error":
      return (
        <ErrorState
          message={resolveErrorMessage(slot.error, t("state.loadFailed"))}
          action={
            slot.retry ? (
              <Button variant="secondary" size="sm" onClick={slot.retry}>
                {t("state.retry")}
              </Button>
            ) : null
          }
        />
      );

    case "noResults":
      return <>{noResults ?? empty}</>;

    case "empty":
      return <>{empty}</>;

    case "data":
      return <>{children(slot.data)}</>;
  }
}
