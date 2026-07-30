import clsx from "clsx";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "./Button";
import { Skeleton } from "./Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "./Table";
import { resolveAsyncSlot, resolveErrorMessage, type AsyncState } from "./asyncState";

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "start" | "end";
  /** Tailwind width class, e.g. "w-32". */
  width?: string;
  className?: string;
  cell: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: ReadonlyArray<Column<T>>;
  rowKey: (row: T) => string;
  /** Supply either resolved rows… */
  rows?: readonly T[];
  /** …or an async state, in which case the table keeps its header mounted and
   *  renders the loading / error / empty ladder in the body (decision 3B). */
  state?: AsyncState<readonly T[]>;
  filtered?: boolean;
  empty?: ReactNode;
  noResults?: ReactNode;
  /** Page-specific failure copy. Falls back to the problem detail carried by
   *  the error, then to a generic message. Worth setting: a raw
   *  `Error("Network Error")` is not something to show an operator. */
  errorMessage?: ReactNode;
  skeletonRows?: number;
  /** Decision 1C: renders the identity cell as a real <Link> AND makes the
   *  whole row clickable. */
  rowHref?: (row: T) => string;
  /** Which column carries the link. Defaults to the first. */
  identityKey?: string;
  /** Extra row click behaviour (used instead of navigation when no href). */
  onRowClick?: (row: T) => void;
  caption?: string;
  className?: string;
}

/*
 * Decision 1C — both row-click and a real link.
 *
 * Whole-row `onClick` alone silently breaks middle-click, ⌘-click, "copy link
 * address" and tab-order; a link in the identity cell alone leaves 90% of the
 * row as dead space. So the identity cell gets a genuine <Link> (which is what
 * keyboard and mouse-modifier users actually use) and the row handler is pure
 * convenience layered on top.
 *
 * The one real cost of that combination is that in-row action buttons must
 * stop propagation, or "Archive" also navigates. That lives here in
 * <RowActions> rather than in each page, so it can't be forgotten.
 */
export function DataTable<T>({
  columns,
  rowKey,
  rows,
  state,
  filtered,
  empty,
  noResults,
  errorMessage,
  skeletonRows = 3,
  rowHref,
  identityKey,
  onRowClick,
  caption,
  className,
}: DataTableProps<T>): ReactNode {
  const { t, i18n } = useTranslation("common");
  const navigate = useNavigate();
  const isRtl = i18n.dir() === "rtl";

  const identity = identityKey ?? columns[0]?.key;
  const interactive = Boolean(rowHref ?? onRowClick);
  const colSpan = columns.length + (rowHref ? 1 : 0);

  const slot = state
    ? resolveAsyncSlot(state, { filtered })
    : ({ kind: "data", data: rows ?? [] } as const);

  function handleRowClick(row: T, event: MouseEvent<HTMLTableRowElement>): void {
    // Let the real <Link> (and any modifier-click on it) do its own job.
    if ((event.target as HTMLElement).closest("a,button,input,select,textarea")) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    if (onRowClick) {
      onRowClick(row);
      return;
    }
    const href = rowHref?.(row);
    if (href) navigate(href);
  }

  function renderCell(column: Column<T>, row: T): ReactNode {
    const content = column.cell(row);
    if (rowHref && column.key === identity) {
      return (
        <Link
          to={rowHref(row)}
          className="font-medium text-ap-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          {content}
        </Link>
      );
    }
    return content;
  }

  return (
    <Table className={className}>
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      <Thead>
        <tr>
          {columns.map((c) => (
            <Th key={c.key} className={clsx(c.align === "end" && "text-end", c.width, c.className)}>
              {c.header}
            </Th>
          ))}
          {rowHref ? (
            <Th className="w-8">
              <span className="sr-only">{t("table.openRow")}</span>
            </Th>
          ) : null}
        </tr>
      </Thead>
      <Tbody>
        {slot.kind === "loading" ? (
          // Decision 3B: header and toolbar are known before the request
          // resolves, so only the rows shimmer. Page height holds steady and
          // nothing shifts when the data lands.
          Array.from({ length: skeletonRows }, (_, i) => (
            <tr key={`sk-${i}`}>
              {columns.map((c) => (
                <Td key={c.key}>
                  <Skeleton className="h-4 w-full max-w-[12rem]" />
                </Td>
              ))}
              {rowHref ? <Td /> : null}
            </tr>
          ))
        ) : slot.kind === "error" ? (
          <tr>
            <Td colSpan={colSpan} className="py-8">
              <div role="alert" className="flex flex-col items-center gap-3 text-center">
                <span className="text-sm text-ap-crit">
                  {errorMessage ?? resolveErrorMessage(slot.error, t("state.loadFailed"))}
                </span>
                {slot.retry ? (
                  <Button variant="secondary" size="sm" onClick={slot.retry}>
                    {t("state.retry")}
                  </Button>
                ) : null}
              </div>
            </Td>
          </tr>
        ) : slot.kind === "empty" || slot.kind === "noResults" ? (
          <tr>
            <Td colSpan={colSpan} className="p-0">
              {slot.kind === "noResults" ? (noResults ?? empty) : empty}
            </Td>
          </tr>
        ) : (
          slot.data.map((row) => (
            /* The row handler is a convenience layer over the real <Link> in
               the identity cell, which is what carries keyboard access. No
               tabindex here on purpose — it would put every row in the tab
               order twice. */
            <Tr
              key={rowKey(row)}
              interactive={interactive}
              onClick={interactive ? (e) => handleRowClick(row, e) : undefined}
            >
              {columns.map((c) => (
                <Td key={c.key} className={clsx(c.align === "end" && "text-end", c.className)}>
                  {renderCell(c, row)}
                </Td>
              ))}
              {rowHref ? (
                <Td className="text-end text-ap-muted" aria-hidden="true">
                  {isRtl ? "‹" : "›"}
                </Td>
              ) : null}
            </Tr>
          ))
        )}
      </Tbody>
    </Table>
  );
}

/**
 * Wrap in-row controls so a click on them doesn't also fire the row's
 * navigation. Required for any interactive cell content inside a
 * `<DataTable>` that has `rowHref` or `onRowClick`.
 */
export function RowActions({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <div
      className={clsx("flex items-center justify-end gap-2", className)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e: KeyboardEvent) => e.stopPropagation()}
      role="presentation"
    >
      {children}
    </div>
  );
}
