import clsx from "clsx";
import type { ReactNode } from "react";

interface KPICardProps {
  title: string;
  value: ReactNode;
  hint?: ReactNode;
  delta?: ReactNode;
  sparkline?: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function KPICard({
  title,
  value,
  hint,
  delta,
  sparkline,
  onClick,
  className,
}: KPICardProps): ReactNode {
  const interactive = typeof onClick === "function";
  const Wrapper = interactive ? "button" : "div";
  return (
    <Wrapper
      type={interactive ? "button" : undefined}
      onClick={onClick}
      className={clsx(
        "block w-full rounded-xl border border-ap-line bg-ap-panel p-4 text-start transition-shadow",
        interactive
          ? "cursor-pointer hover:shadow-card focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
          : "",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
          {title}
        </div>
        {delta ? <div className="text-xs font-medium">{delta}</div> : null}
      </div>
      <div className="mt-2 text-3xl font-semibold text-ap-ink">{value}</div>
      {hint ? <div className="mt-1 text-xs text-ap-muted">{hint}</div> : null}
      {sparkline ? <div className="mt-3">{sparkline}</div> : null}
    </Wrapper>
  );
}
