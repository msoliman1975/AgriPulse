import clsx from "clsx";
import { forwardRef } from "react";
import type { FormEventHandler, HTMLAttributes, ReactNode } from "react";

type CardElement = "div" | "section" | "aside" | "form";

interface CardProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /**
   * The element to render. Defaults to `div`.
   *
   * `form` matters: a card that wraps a form IS the form. Rendering a div
   * instead silently drops submission — no error, no type complaint, the
   * button just stops working.
   */
  as?: CardElement;
  onSubmit?: FormEventHandler<HTMLFormElement>;
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
export const Card = forwardRef<HTMLElement, CardProps>(function Card(
  {
    as: Tag = "div",
    noPadding = false,
    title,
    actions,
    footer,
    bodyClassName,
    className,
    children,
    ...rest
  },
  ref,
): ReactNode {
  const hasChrome = Boolean(title ?? footer);
  const bodyPadding = noPadding ? null : "p-4";

  return (
    // `Tag` is a union of intrinsic elements, so TS can't reconcile the props
    // bag against any single one of them. The public surface above is the
    // contract; this cast is where the polymorphism is paid for.
    <Tag
      ref={ref as never}
      className={clsx(
        "rounded-card border border-ap-line bg-ap-panel",
        !hasChrome && bodyPadding,
        className,
      )}
      {...(rest as Record<string, unknown>)}
    >
      {title ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ap-line px-4 py-2.5">
          <h2 className="text-card-title font-semibold text-ap-ink">{title}</h2>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {hasChrome ? <div className={clsx(bodyPadding, bodyClassName)}>{children}</div> : children}
      {footer}
    </Tag>
  );
});
