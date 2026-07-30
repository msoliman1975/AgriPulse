import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { BUTTON_BASE_CLASS, SIZE_CLASS, VARIANT_CLASS } from "./buttonStyles";
import type { ButtonSize, ButtonVariant } from "./buttonStyles";

export type { ButtonSize, ButtonVariant };

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

// The single source of truth for button styling. Before this, ~35 surfaces
// hand-rolled `bg-ap-primary px-3 py-1.5…` with inconsistent padding and font
// size (F-6). Navigations use <LinkButton>, which shares these exact classes —
// that gap is why this component had no adopters for its first two months.
export function Button({
  variant = "primary",
  size = "md",
  type = "button",
  className,
  children,
  ...rest
}: ButtonProps): ReactNode {
  return (
    <button
      type={type}
      className={clsx(BUTTON_BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
      {...rest}
    >
      {children}
    </button>
  );
}
