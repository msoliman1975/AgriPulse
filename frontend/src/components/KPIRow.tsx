import clsx from "clsx";
import type { ReactNode } from "react";

interface KPIRowProps {
  children: ReactNode;
  /** Column count at the widest breakpoint. Defaults to 3. */
  columns?: 2 | 3 | 4;
  className?: string;
}

const COLUMN_CLASS: Record<2 | 3 | 4, string> = {
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-4",
};

/** Responsive grid wrapper for `<KPICard>`s on a detail page or dashboard. */
export function KPIRow({ children, columns = 3, className }: KPIRowProps): ReactNode {
  return (
    <div className={clsx("grid grid-cols-1 gap-3", COLUMN_CLASS[columns], className)}>
      {children}
    </div>
  );
}
