import clsx from "clsx";
import type { ReactNode } from "react";

interface DataPendingChipProps {
  children?: ReactNode;
  className?: string;
}

/**
 * Small chip used wherever a backing field is in transition (column added
 * but not yet populated, sweep job hasn't fired, etc.). Currently used for
 * `alerts.prescription_activity_id` until the engine starts emitting it.
 */
export function DataPendingChip({ children, className }: DataPendingChipProps): ReactNode {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full bg-ap-line/60 px-2 py-0.5 text-[11px] font-medium text-ap-muted",
        className,
      )}
      role="status"
    >
      <span aria-hidden="true">…</span>
      {children ?? "Data computing"}
    </span>
  );
}
