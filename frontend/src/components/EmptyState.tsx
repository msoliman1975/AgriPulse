import clsx from "clsx";
import type { ReactNode } from "react";

interface EmptyStateProps {
  message: ReactNode;
  /** Optional next-step CTA (a link or button). Good empty states offer one (F-8). */
  action?: ReactNode;
  className?: string;
}

// The canonical "nothing here yet" surface: centered muted text, optionally
// followed by a next-step CTA. Standardizes the p-12 centered-text pattern
// (≈12 pages already use it) and makes the CTA a first-class slot.
export function EmptyState({ message, action, className }: EmptyStateProps): ReactNode {
  return (
    <div
      className={clsx(
        "flex flex-col items-center gap-3 p-12 text-center text-sm text-ap-muted",
        className,
      )}
    >
      <p>{message}</p>
      {action}
    </div>
  );
}
