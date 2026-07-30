import clsx from "clsx";
import type { ReactNode } from "react";

export type StatusBannerKind = "info" | "warn" | "crit";

const KIND_CLASS: Record<StatusBannerKind, string> = {
  info: "border-ap-accent/30 bg-ap-accent/10 text-ap-accent",
  warn: "border-ap-warn/30 bg-ap-warn-soft text-ap-warn",
  crit: "border-ap-crit/30 bg-ap-crit-soft text-ap-crit",
};

interface StatusBannerProps {
  kind?: StatusBannerKind;
  children: ReactNode;
  /** Secondary line, e.g. the reason a tenant was suspended. */
  detail?: ReactNode;
  className?: string;
}

/**
 * The "this entity is in a notable state" strip on detail pages. Extracted
 * from `TenantAdminDetailPage`, which was the only page that had one.
 *
 * `role="status"` not `role="alert"` — this describes standing state, not a
 * failure that just happened. `<ErrorState>` is the one that interrupts.
 */
export function StatusBanner({
  kind = "info",
  children,
  detail,
  className,
}: StatusBannerProps): ReactNode {
  return (
    <div
      role="status"
      className={clsx("rounded-xl border p-3 text-sm", KIND_CLASS[kind], className)}
    >
      {children}
      {detail ? <p className="mt-1 text-xs opacity-80">{detail}</p> : null}
    </div>
  );
}
