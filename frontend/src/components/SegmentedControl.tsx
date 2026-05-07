import clsx from "clsx";
import type { ReactNode } from "react";

export interface SegmentedControlItem<T extends string> {
  value: T;
  label: ReactNode;
}

interface SegmentedControlProps<T extends string> {
  items: ReadonlyArray<SegmentedControlItem<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}

export function SegmentedControl<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className,
}: SegmentedControlProps<T>): ReactNode {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={clsx("inline-flex rounded-lg border border-ap-line bg-ap-panel p-0.5", className)}
    >
      {items.map((item) => {
        const isActive = item.value === value;
        return (
          <button
            type="button"
            role="radio"
            aria-checked={isActive}
            key={item.value}
            onClick={() => onChange(item.value)}
            className={clsx(
              "rounded-md px-3 py-1 text-xs font-medium transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary",
              isActive
                ? "bg-ap-ink text-white"
                : "text-ap-muted hover:bg-ap-line/40",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
