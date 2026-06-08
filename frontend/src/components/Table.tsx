import clsx from "clsx";
import type {
  HTMLAttributes,
  TdHTMLAttributes,
  ThHTMLAttributes,
} from "react";
import type { ReactNode } from "react";

/*
 * Composable table primitives. The app had 21 hand-rolled <table> blocks with
 * divergent header backgrounds (bg-ap-line/30 vs bg-ap-bg/40), padding, and
 * row hover (F-6). These wrap the native elements with the one agreed style so
 * tables can be migrated tag-for-tag (<table> -> <Table>, <thead> -> <Thead>…).
 */

export function Table({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLTableElement>): ReactNode {
  return (
    <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
      <table
        className={clsx("min-w-full divide-y divide-ap-line text-sm", className)}
        {...rest}
      >
        {children}
      </table>
    </div>
  );
}

export function Thead({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLTableSectionElement>): ReactNode {
  return (
    <thead
      className={clsx(
        "bg-ap-bg/40 text-[11px] uppercase tracking-wider text-ap-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </thead>
  );
}

export function Tbody({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLTableSectionElement>): ReactNode {
  return (
    <tbody className={clsx("divide-y divide-ap-line", className)} {...rest}>
      {children}
    </tbody>
  );
}

interface TrProps extends HTMLAttributes<HTMLTableRowElement> {
  /** Adds pointer + hover affordance for clickable rows. */
  interactive?: boolean;
}

export function Tr({
  interactive = false,
  className,
  children,
  ...rest
}: TrProps): ReactNode {
  return (
    <tr
      className={clsx(
        interactive && "cursor-pointer transition-colors hover:bg-ap-line/30",
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function Th({
  className,
  children,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement>): ReactNode {
  return (
    <th
      scope="col"
      className={clsx("px-3 py-2 text-start font-semibold", className)}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({
  className,
  children,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement>): ReactNode {
  return (
    <td className={clsx("px-3 py-2", className)} {...rest}>
      {children}
    </td>
  );
}
