import clsx from "clsx";
import type { ReactNode } from "react";

interface FilterChipProps {
  active: boolean;
  onToggle: () => void;
  children: ReactNode;
  swatchClassName?: string;
  className?: string;
}

export function FilterChip({
  active,
  onToggle,
  children,
  swatchClassName,
  className,
}: FilterChipProps): ReactNode {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      onClick={onToggle}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary",
        active
          ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
          : "border-ap-line bg-ap-panel text-ap-muted hover:bg-ap-line/40",
        className,
      )}
    >
      {swatchClassName ? (
        <span aria-hidden="true" className={clsx("h-2 w-2 rounded-sm", swatchClassName)} />
      ) : null}
      {children}
    </button>
  );
}
