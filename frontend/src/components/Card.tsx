import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** Drop the default `p-4` body padding (e.g. when the card wraps a table). */
  noPadding?: boolean;
  /** Renders a bordered header strip. Replaces the local `Card` in
   *  TenantAdminDetailPage and BlockDefaultsPanel, both of which existed only
   *  because the shared Card had no title slot. */
  title?: ReactNode;
  /** Right-aligned controls in the header strip. */
  actions?: ReactNode;
  /** Bordered footer strip, typically form or panel actions. */
  footer?: ReactNode;
  /** Applied to the body wrapper when `title`/`footer` are used. */
  bodyClassName?: string;
}

// The canonical panel surface. ~150 inline copies of
// `rounded-xl border border-ap-line bg-ap-panel` existed across the app (F-6),
// plus a competing `rounded-lg … shadow-card` variant declared locally on the
// tenant detail page. One radius, one border, no elevation.
export function Card({
  noPadding = false,
  title,
  actions,
  footer,
  bodyClassName,
  className,
  children,
  ...rest
}: CardProps): ReactNode {
  const hasChrome = Boolean(title ?? footer);
  const bodyPadding = noPadding ? null : "p-4";

  return (
    <div
      className={clsx(
        "rounded-xl border border-ap-line bg-ap-panel",
        !hasChrome && bodyPadding,
        className,
      )}
      {...rest}
    >
      {title ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ap-line px-4 py-2.5">
          <h2 className="text-sm font-semibold text-ap-ink">{title}</h2>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {hasChrome ? <div className={clsx(bodyPadding, bodyClassName)}>{children}</div> : children}
      {footer}
    </div>
  );
}
