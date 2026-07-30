export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

/*
 * Button styling lives here rather than in Button.tsx so <LinkButton> can
 * share it verbatim. Keeping these in the .tsx would trip
 * `react-refresh/only-export-components`, and duplicating them is exactly
 * the drift this component set exists to stop.
 */
export const BUTTON_BASE_CLASS =
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary focus-visible:ring-offset-1 " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "bg-ap-primary text-white hover:bg-ap-primary/90",
  secondary: "border border-ap-line bg-ap-panel text-ap-ink hover:bg-ap-line/40",
  ghost: "text-ap-ink hover:bg-ap-line/50",
  danger: "bg-ap-crit text-white hover:bg-ap-crit/90",
};

export const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
};
