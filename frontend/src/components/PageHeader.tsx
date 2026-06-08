import clsx from "clsx";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned actions (buttons, links, toggles). */
  actions?: ReactNode;
  /** Optional content rendered above the title — e.g. a back link / breadcrumb. */
  above?: ReactNode;
  className?: string;
}

// Standardizes the page H1. Titles drifted across `text-2xl` / `text-xl` /
// `text-lg` and `text-ap-ink` / legacy `text-brand-800` (F-11). Use this for
// every page heading so the scale and color stay consistent.
export function PageHeader({
  title,
  subtitle,
  actions,
  above,
  className,
}: PageHeaderProps): ReactNode {
  return (
    <header className={clsx("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {above ? <div className="mb-1">{above}</div> : null}
        <h1 className="text-2xl font-semibold text-ap-ink">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ap-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
