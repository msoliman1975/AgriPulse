import clsx from "clsx";
import type { ReactNode } from "react";

interface ErrorStateProps {
  message: ReactNode;
  /** Optional recovery action, e.g. a "Retry" button. */
  action?: ReactNode;
  className?: string;
}

// The canonical "request failed" surface. Replaces three competing idioms
// (F-9): bare inline `text-ap-crit`, the admin module's accessible-but-
// off-palette rose box, and the farms module's unstyled `text-red-700`.
// Keeps the admin pattern's `role="alert"` + bordered box (the accessible
// part) but on the `ap-crit` tokens.
export function ErrorState({ message, action, className }: ErrorStateProps): ReactNode {
  return (
    <div
      role="alert"
      className={clsx(
        "flex flex-wrap items-center gap-3 rounded-md border border-ap-crit/30 bg-ap-crit-soft p-4 text-sm text-ap-crit",
        className,
      )}
    >
      <span className="flex-1">{message}</span>
      {action}
    </div>
  );
}
