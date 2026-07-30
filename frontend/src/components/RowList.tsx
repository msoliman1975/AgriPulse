import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button } from "./Button";
import { Card } from "./Card";
import { Skeleton } from "./Skeleton";
import { resolveAsyncSlot, resolveErrorMessage, type AsyncState } from "./asyncState";

interface RowListProps<T> {
  items?: readonly T[];
  state?: AsyncState<readonly T[]>;
  rowKey: (item: T) => string;
  /** Tailwind background class for the leading severity/type rail. */
  rail?: (item: T) => string | undefined;
  title: (item: T) => ReactNode;
  subtitle?: (item: T) => ReactNode;
  meta?: (item: T) => ReactNode;
  /** Full-width block below the meta line — expandable detail, nested lists. */
  extra?: (item: T) => ReactNode;
  actions?: (item: T) => ReactNode;
  href?: (item: T) => string;
  filtered?: boolean;
  empty: ReactNode;
  noResults?: ReactNode;
  /** Page-specific failure copy; falls back to the error's own detail. */
  errorMessage?: ReactNode;
  skeletonRows?: number;
  className?: string;
}

/*
 * The card/row-list body for index pages whose rows are too tall for a table
 * (P2): alerts, recommendations, signals, crops.
 *
 * `AlertsPage` and `RecommendationsPage` were 200-line near-duplicates of each
 * other — same wrapper, same four-branch ladder, same `ul.divide-y`, differing
 * only in row content. This is that shape, once.
 */
export function RowList<T>({
  items,
  state,
  rowKey,
  rail,
  title,
  subtitle,
  meta,
  extra,
  actions,
  href,
  filtered,
  empty,
  noResults,
  errorMessage,
  skeletonRows = 3,
  className,
}: RowListProps<T>): ReactNode {
  const { t } = useTranslation("common");
  const slot = state
    ? resolveAsyncSlot(state, { filtered })
    : ({ kind: "data", data: items ?? [] } as const);

  if (slot.kind === "loading") {
    return (
      <Card noPadding className={clsx("flex flex-col gap-2 p-4", className)}>
        {Array.from({ length: skeletonRows }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded-lg" />
        ))}
      </Card>
    );
  }

  if (slot.kind === "error") {
    return (
      <Card noPadding className={className}>
        <div role="alert" className="flex flex-col items-center gap-3 p-8 text-center">
          <span className="text-sm text-ap-crit">
            {errorMessage ?? resolveErrorMessage(slot.error, t("state.loadFailed"))}
          </span>
          {slot.retry ? (
            <Button variant="secondary" size="sm" onClick={slot.retry}>
              {t("state.retry")}
            </Button>
          ) : null}
        </div>
      </Card>
    );
  }

  if (slot.kind === "empty" || slot.kind === "noResults") {
    return (
      <Card noPadding className={className}>
        {slot.kind === "noResults" ? (noResults ?? empty) : empty}
      </Card>
    );
  }

  return (
    <Card noPadding className={className}>
      <ul className="divide-y divide-ap-line">
        {slot.data.map((item) => {
          const railClass = rail?.(item);
          const to = href?.(item);
          const heading = title(item);
          return (
            <li key={rowKey(item)} className="flex items-start gap-3 p-4">
              {railClass ? (
                <span
                  aria-hidden="true"
                  className={clsx(
                    "min-h-[2.5rem] w-1 flex-none self-stretch rounded-full",
                    railClass,
                  )}
                />
              ) : null}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-ap-ink">
                  {to ? (
                    <Link to={to} className="text-ap-primary hover:underline">
                      {heading}
                    </Link>
                  ) : (
                    heading
                  )}
                </div>
                {subtitle ? (
                  <div className="mt-1 text-sm text-ap-muted">{subtitle(item)}</div>
                ) : null}
                {meta ? (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ap-muted">
                    {meta(item)}
                  </div>
                ) : null}
                {extra ? extra(item) : null}
              </div>
              {actions ? (
                <div className="flex flex-none items-center gap-2">{actions(item)}</div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
