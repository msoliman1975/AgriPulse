import clsx from "clsx";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: ReactNode;
  /** Status pill rendered inline with the title (decision 4C). Keeps "what
   *  state is this thing in" at the same altitude as its name. */
  badge?: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned actions. Destructive ones go last. */
  actions?: ReactNode;
  /** Content above the title — a `<Breadcrumb>`, which is the single
   *  wayfinding idiom (F-7). */
  above?: ReactNode;
  className?: string;
}

// Standardizes the page H1. Titles drifted across `text-2xl` / `text-xl` /
// `text-lg` / `text-base` / `text-sm` and `text-ap-ink` / legacy
// `text-brand-800` (F-11). One scale everywhere — including detail pages,
// which previously stepped *down* to `text-lg` and so read as lesser than the
// list they were opened from.
export function PageHeader({
  title,
  badge,
  subtitle,
  actions,
  above,
  className,
}: PageHeaderProps): ReactNode {
  return (
    <header className={clsx("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {above ? <div className="mb-1">{above}</div> : null}
        <h1 className="flex flex-wrap items-center gap-2.5 text-2xl font-semibold text-ap-ink">
          {title}
          {badge}
        </h1>
        {subtitle ? <p className="mt-1 text-sm text-ap-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
