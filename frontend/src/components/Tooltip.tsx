import type { ReactElement, ReactNode } from "react";
import { cloneElement, useCallback, useLayoutEffect, useRef, useState } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  className?: string;
}

interface Placement {
  top: number;
  left: number;
}

/** Gap between the trigger and the bubble, and the minimum viewport inset. */
const MARGIN = 8;

/**
 * Lightweight tooltip — hover and focus, no dependency.
 *
 * Positioned **fixed** and measured from the trigger, rather than absolutely
 * inside the trigger's own box. That is not a style preference: `Table` wraps
 * every table in `overflow-x-auto`, and CSS promotes the other axis to a
 * clipping value when one axis is `auto`, so a bubble drawn above a `<thead>`
 * cell was clipped away entirely.
 *
 * Escaping the clipping box is only half of it. The bubble also has to *fit*:
 *
 *   - it wraps (`whitespace-normal` + `max-w-xs`), because a long description
 *     forced onto one line runs off the screen;
 *   - it is clamped into the viewport horizontally, so a hint on the
 *     right-most column is not cut off at the window edge;
 *   - it flips below the trigger when there is no room above, which is the
 *     common case for a header near the top of the page.
 *
 * The geometry is measured after paint, so the bubble stays hidden for one
 * frame rather than flashing at an unplaced position.
 *
 * **Do not add a `whitespace-*` or width utility to the base classes below.**
 * Tailwind emits `whitespace-nowrap` after `whitespace-normal`, so a base
 * `nowrap` silently beats a caller's `whitespace-normal` no matter what order
 * the class strings are concatenated in — which is exactly how the header
 * hints ended up truncated.
 */
export function Tooltip({ content, children, className }: TooltipProps): ReactNode {
  const anchor = useRef<HTMLSpanElement | null>(null);
  const bubble = useRef<HTMLSpanElement | null>(null);
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement | null>(null);

  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => {
    setOpen(false);
    setPlacement(null);
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const trigger = anchor.current?.getBoundingClientRect();
    const box = bubble.current?.getBoundingClientRect();
    if (!trigger || !box) return;

    // Above by default; below when the bubble would overrun the top edge.
    const fitsAbove = trigger.top - MARGIN - box.height >= 0;
    const top = fitsAbove ? trigger.top - MARGIN - box.height : trigger.bottom + MARGIN;

    // Centre on the trigger, then pull back inside the viewport. Without this
    // a hint on the last column is drawn half off-screen.
    const centred = trigger.left + trigger.width / 2 - box.width / 2;
    const left = Math.max(
      MARGIN,
      Math.min(centred, document.documentElement.clientWidth - box.width - MARGIN),
    );

    setPlacement({ top, left });
  }, [open, content]);

  const handlers = {
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  };

  return (
    <span ref={anchor} className="relative inline-flex">
      {cloneElement(children, handlers)}
      {open ? (
        <span
          ref={bubble}
          role="tooltip"
          style={{
            top: placement?.top ?? 0,
            left: placement?.left ?? 0,
            // Hidden, not unmounted, for the frame before measurement — the
            // bubble has to be in the DOM to have a size to measure.
            visibility: placement ? "visible" : "hidden",
          }}
          className={`pointer-events-none fixed z-50 max-w-xs whitespace-normal break-words rounded bg-ap-ink px-2 py-1 text-start text-xs text-white shadow-card ${className ?? ""}`}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
