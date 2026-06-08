import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

// The single source of truth for button styling. Before this, ~35 surfaces
// hand-rolled `bg-ap-primary px-3 py-1.5…` with inconsistent padding and font
// size (F-6). Route new buttons through here so the drift stops compounding.
const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "bg-ap-primary text-white hover:bg-ap-primary/90",
  secondary:
    "border border-ap-line bg-ap-panel text-ap-ink hover:bg-ap-line/40",
  ghost: "text-ap-ink hover:bg-ap-line/50",
  danger: "bg-ap-crit text-white hover:bg-ap-crit/90",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
};

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
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
