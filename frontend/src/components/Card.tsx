import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Drop the default `p-4` body padding (e.g. when the card wraps a table). */
  noPadding?: boolean;
}

// The canonical panel surface. ~150 inline copies of
// `rounded-xl border border-ap-line bg-ap-panel` exist across the app (F-6);
// new panels should use this so radius, border, and background stay uniform.
export function Card({
  noPadding = false,
  className,
  children,
  ...rest
}: CardProps): ReactNode {
  return (
    <div
      className={clsx(
        "rounded-xl border border-ap-line bg-ap-panel",
        noPadding ? null : "p-4",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
