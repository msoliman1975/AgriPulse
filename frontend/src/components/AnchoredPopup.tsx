import clsx from "clsx";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  // Click pixel coords (relative to the map container) — anchor the card
  // next to the clicked point. Null falls back to the fixed top-right corner.
  x: number | null;
  y: number | null;
  // Descriptive chrome shared by every anchored popup: an uppercase muted
  // title and an optional bolder subtitle line.
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  widthClass?: string;
}

// Offset the card from the click point so it doesn't sit under the cursor.
const ANCHOR_OFFSET = 10;
// Keep the card at least this far from the parent container's edges.
const EDGE_PAD = 4;

/**
 * Shared anchored-popup wrapper — the single source of look + behaviour for
 * the map's click popups (grid cell, signal observation). It owns the
 * card chrome (border/panel/shadow), the descriptive title/subtitle header,
 * the close button, and the click-anchoring maths (measure the card + its
 * offsetParent, flip on overflow, clamp inside the container). When `x`/`y`
 * are null it pins to the fixed top-right corner instead.
 */
export function AnchoredPopup({
  x,
  y,
  title,
  subtitle,
  onClose,
  children,
  widthClass,
}: Props): ReactNode {
  const anchored = x !== null && y !== null;
  const cardRef = useRef<HTMLDivElement | null>(null);
  // Adjusted (clamped/flipped) position once we can measure the card. Until
  // then we render at the raw offset to avoid a frame at (0,0).
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!anchored || x === null || y === null) {
      setPos(null);
      return;
    }
    const card = cardRef.current;
    // offsetParent is the nearest positioned ancestor — the map container
    // (`relative flex-1 overflow-hidden`) that wraps both the canvas and
    // this popup, so its rect shares the same coordinate space as `x`/`y`.
    const parent = card?.offsetParent as HTMLElement | null;
    if (!card || !parent) return;
    const cardRect = card.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    const w = cardRect.width;
    const h = cardRect.height;
    const maxLeft = parentRect.width - w - EDGE_PAD;
    const maxTop = parentRect.height - h - EDGE_PAD;

    let left = x + ANCHOR_OFFSET;
    let top = y + ANCHOR_OFFSET;
    // If we'd overflow the right edge, flip to the left of the click.
    if (left > maxLeft) left = x - w - ANCHOR_OFFSET;
    // If we'd overflow the bottom edge, flip above the click.
    if (top > maxTop) top = y - h - ANCHOR_OFFSET;
    // Clamp inside the container regardless (covers tiny containers / flips
    // that still overshoot).
    left = Math.max(EDGE_PAD, Math.min(left, maxLeft));
    top = Math.max(EDGE_PAD, Math.min(top, maxTop));
    setPos({ left, top });
  }, [anchored, x, y, title, subtitle, children]);

  // When anchored, position via inline style (and drop the fixed-corner
  // Tailwind classes). Until measured, render at the raw offset.
  const anchorStyle =
    anchored && x !== null && y !== null
      ? ({
          position: "absolute",
          left: pos?.left ?? x + ANCHOR_OFFSET,
          top: pos?.top ?? y + ANCHOR_OFFSET,
        } as const)
      : undefined;

  return (
    <div
      ref={cardRef}
      style={anchorStyle}
      className={clsx(
        "pointer-events-auto absolute z-30 rounded-md border border-ap-line bg-ap-panel p-3 text-xs shadow-lg",
        widthClass ?? "w-64",
        !anchored && "top-14 end-4",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ap-muted">{title}</p>
          {subtitle ? (
            <p className="truncate text-[15px] font-semibold text-ap-ink" title={subtitle}>
              {subtitle}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded p-0.5 text-ap-muted hover:bg-ap-bg hover:text-ap-ink"
        >
          ✕
        </button>
      </div>
      {children}
    </div>
  );
}
