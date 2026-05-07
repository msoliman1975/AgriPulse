import type { ReactElement, ReactNode } from "react";
import { cloneElement, useState } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  className?: string;
}

/**
 * Lightweight CSS-only tooltip — renders content as a positioned span next
 * to the trigger element. Honors hover and focus. For modal-grade tooltips
 * (rich content, repositioning) replace with a Floating-UI implementation.
 */
export function Tooltip({ content, children, className }: TooltipProps): ReactNode {
  const [open, setOpen] = useState(false);
  const handlers = {
    onMouseEnter: () => setOpen(true),
    onMouseLeave: () => setOpen(false),
    onFocus: () => setOpen(true),
    onBlur: () => setOpen(false),
  };
  return (
    <span className="relative inline-flex">
      {cloneElement(children, handlers)}
      {open ? (
        <span
          role="tooltip"
          className={`pointer-events-none absolute -top-2 left-1/2 z-50 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded bg-ap-ink px-2 py-1 text-xs text-white shadow-card ${className ?? ""}`}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
