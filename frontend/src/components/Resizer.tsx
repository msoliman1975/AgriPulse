// A drag handle between two panels.
//
// The Farm Health View puts a rail, a map and a detail panel on one screen,
// and no single split suits both a block with one whole-block sentence and a
// block with eleven areas. So the reader moves the boundary instead.
//
// Pointer events, not mouse events: the same code then works with a finger
// and a stylus, and `setPointerCapture` keeps the drag alive when the
// pointer leaves the 6px handle, which it does immediately.
//
// It is a real `separator` with arrow keys, not a div with a cursor. A
// keyboard reader gets the same control, and a screen reader is told the
// size rather than being told there is a handle here.

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  /**
   * Which way the handle moves.
   *
   * "vertical" is a vertical bar dragged left and right, which resizes a
   * width; "horizontal" is a horizontal bar dragged up and down, which
   * resizes a height. This names the BAR, the way `aria-orientation` does.
   */
  orientation: "vertical" | "horizontal";
  /** The current size, in CSS pixels, of the panel this handle sizes. */
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
  /** What the handle resizes, said in words. Becomes the accessible name. */
  label: string;
  /**
   * True when the panel being sized is AFTER the handle, so dragging the
   * handle one way grows it and the arithmetic flips.
   */
  reversed?: boolean;
}

/** One arrow press. A tenth of that would take fifty presses to matter. */
const STEP = 24;

export function Resizer({ orientation, value, min, max, onChange, label, reversed }: Props) {
  const vertical = orientation === "vertical";
  const [dragging, setDragging] = useState(false);
  // The drag reads the size it started from, not the prop: the prop is a
  // render behind while a pointer is moving, and adding each delta to a
  // stale value makes the panel crawl instead of following the pointer.
  const start = useRef({ pointer: 0, size: 0 });

  const clamp = useCallback(
    (next: number) => Math.min(max, Math.max(min, Math.round(next))),
    [min, max],
  );

  // While dragging, the cursor is the handle's wherever the pointer is, and
  // nothing on the page selects. Set on the document because the pointer is
  // usually over the map or the panel, not over the 6px handle.
  useEffect(() => {
    if (!dragging) return undefined;
    const body = document.body;
    const previousCursor = body.style.cursor;
    const previousSelect = body.style.userSelect;
    body.style.cursor = vertical ? "col-resize" : "row-resize";
    body.style.userSelect = "none";
    return () => {
      body.style.cursor = previousCursor;
      body.style.userSelect = previousSelect;
    };
  }, [dragging, vertical]);

  return (
    // A separator carrying `aria-valuenow` is ARIA's window splitter, and a
    // window splitter is focusable and takes arrow keys — that is the whole
    // pattern. jsx-a11y classes every separator as non-interactive, so it
    // reads the tabIndex and the key handler here as mistakes.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="separator"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={label}
      aria-orientation={orientation}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      data-testid={`resizer-${orientation}`}
      onPointerDown={(event) => {
        // Secondary buttons open menus; they must not start a drag that
        // then has no matching pointerup.
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = { pointer: vertical ? event.clientX : event.clientY, size: value };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (!dragging) return;
        const now = vertical ? event.clientX : event.clientY;
        const delta = (now - start.current.pointer) * (reversed ? -1 : 1);
        onChange(clamp(start.current.size + delta));
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        setDragging(false);
      }}
      onPointerCancel={() => setDragging(false)}
      onKeyDown={(event) => {
        // Physical keys, matched to the physical direction the bar moves.
        // Under RTL the whole layout mirrors, so the key that grows the rail
        // is the one pointing away from it in either direction.
        const grow = vertical ? "ArrowRight" : "ArrowDown";
        const shrink = vertical ? "ArrowLeft" : "ArrowUp";
        const sign = reversed ? -1 : 1;
        if (event.key === grow) onChange(clamp(value + STEP * sign));
        else if (event.key === shrink) onChange(clamp(value - STEP * sign));
        else if (event.key === "Home") onChange(min);
        else if (event.key === "End") onChange(max);
        else return;
        event.preventDefault();
      }}
      className={[
        "group relative shrink-0 bg-ap-line/60 transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary",
        vertical ? "w-1.5 cursor-col-resize" : "h-1.5 cursor-row-resize",
        dragging ? "bg-ap-primary" : "hover:bg-ap-primary/60",
      ].join(" ")}
    >
      {/* A 6px target is under the 24px a finger needs, and widening the bar
          itself would put a grey stripe through the layout. So the bar stays
          thin and the hit area is an invisible overlay around it. */}
      <span
        aria-hidden="true"
        className={
          vertical
            ? "absolute inset-y-0 -inset-x-2.5 block"
            : "absolute inset-x-0 -inset-y-2.5 block"
        }
      />
      {/* The grip. Without it a thin line reads as a border, and nobody
          discovers that it drags. */}
      <span
        aria-hidden="true"
        className={[
          "absolute rounded-full bg-ap-muted/50 group-hover:bg-white",
          // Physical `left`, not logical `start`: the grip is centred on a
          // 6px bar, and a logical inset paired with a physical translate
          // pushes it off the bar entirely under RTL.
          vertical
            ? "left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2"
            : "left-1/2 top-1/2 h-0.5 w-8 -translate-x-1/2 -translate-y-1/2",
        ].join(" ")}
      />
    </div>
  );
}
