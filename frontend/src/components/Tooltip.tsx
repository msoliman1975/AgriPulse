import type { ReactElement, ReactNode } from "react";
import { cloneElement, useCallback, useRef, useState } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  className?: string;
}

interface Position {
  top: number;
  left: number;
}

/**
 * Lightweight tooltip — hover and focus, no dependency.
 *
 * The bubble is positioned **fixed**, measured from the trigger on open,
 * rather than absolutely inside the trigger's own stacking context. That is
 * not a style preference: `Table` wraps every table in
 * `<div class="overflow-x-auto">`, and CSS promotes the other axis to a
 * clipping value whenever one axis is `auto`. A bubble drawn above a `<thead>`
 * cell therefore landed outside the scroll container and was clipped away
 * completely — the column-header hints on /platform/roles rendered their text
 * into the DOM and showed nothing at all, leaving only the `cursor-help`
 * question-mark cursor. `position: fixed` escapes every clipping ancestor.
 *
 * Unclipped callers are unaffected: the bubble still sits centred just above
 * the trigger, so the charts that already used this look identical.
 */
export function Tooltip({ content, children, className }: TooltipProps): ReactNode {
  const anchor = useRef<HTMLSpanElement | null>(null);
  const [position, setPosition] = useState<Position | null>(null);

  const show = useCallback(() => {
    const rect = anchor.current?.getBoundingClientRect();
    if (!rect) return;
    // Viewport coordinates — `fixed` is relative to the viewport, so no scroll
    // offset is added. Re-measured on every open, which keeps it correct after
    // the page scrolls or the table is scrolled sideways.
    setPosition({ top: rect.top - 8, left: rect.left + rect.width / 2 });
  }, []);

  const hide = useCallback(() => setPosition(null), []);

  const handlers = {
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  };

  return (
    <span ref={anchor} className="relative inline-flex">
      {cloneElement(children, handlers)}
      {position ? (
        <span
          role="tooltip"
          style={{ top: position.top, left: position.left, transform: "translate(-50%, -100%)" }}
          className={`pointer-events-none fixed z-50 whitespace-nowrap rounded bg-ap-ink px-2 py-1 text-xs text-white shadow-card ${className ?? ""}`}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
