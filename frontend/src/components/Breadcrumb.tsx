import clsx from "clsx";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export interface Crumb {
  label: ReactNode;
  /** Omit on the current (last) crumb. */
  to?: string;
}

/*
 * Consistent wayfinding for the Tenant -> Farm -> Block -> Cell hierarchy (F-7).
 * The app had ad-hoc "Back" buttons on some detail pages and nothing on others;
 * this renders one breadcrumb trail. Separators use a direction-neutral "/" and
 * logical gaps so the trail flips correctly under dir="rtl".
 */
export function Breadcrumb({
  items,
  className,
}: {
  items: Crumb[];
  className?: string;
}): ReactNode {
  return (
    <nav aria-label="Breadcrumb" className={clsx("text-sm", className)}>
      <ol className="flex flex-wrap items-center gap-1.5 text-ap-muted">
        {items.map((c, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={c.to ?? `crumb-${i}`} className="flex items-center gap-1.5">
              {c.to && !isLast ? (
                <Link to={c.to} className="font-medium text-ap-primary hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span
                  className={isLast ? "text-ap-ink" : undefined}
                  aria-current={isLast ? "page" : undefined}
                >
                  {c.label}
                </span>
              )}
              {!isLast ? (
                <span aria-hidden="true" className="text-ap-muted/60">
                  /
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
