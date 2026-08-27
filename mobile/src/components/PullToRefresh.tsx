import { useEffect, useRef, useState, type ReactNode } from "react";

import { t, type Lang } from "@/i18n";

/**
 * Pull the list down to fetch it again.
 *
 * The app reloads on open and after every action it takes itself, and that was
 * the whole story: a scout whose supervisor assigned them a job while the app
 * sat open on the Tasks screen had no way to see it short of switching tabs
 * and back, or force-quitting. Push is not the answer to this — a dropped
 * notification is normal on a field connection, and the list has always been
 * the source of truth rather than the push. What was missing was a way to ask.
 *
 * Deliberately the ordinary gesture and nothing else. A refresh button in a
 * header is a thing to find; pulling a list down is what everyone already does
 * to a list on a phone, including people who would not read a label.
 *
 * **The page scrolls the document, not a container.** The screens set no
 * overflow of their own, so the guard is `window.scrollY === 0` — the gesture
 * must only start when the list is already at the top, or a scout scrolling up
 * through a long day's work triggers a fetch every time they reach the end.
 *
 * Written by hand rather than pulled in: it is fifty lines, and the libraries
 * that do this assume they own a scroll container, which here is the document.
 */

/** How far the finger travels before the refresh fires. */
const THRESHOLD_PX = 72;
/** How far the indicator is allowed to move. The pull is damped past the
 *  threshold so the gesture cannot be dragged down the whole screen. */
const MAX_PULL_PX = 110;

export function PullToRefresh({
  lang,
  className,
  onRefresh,
  children,
}: {
  lang: Lang;
  /** Classes for the element this renders. The screens hand over their own
   *  `screen …` classes so this REPLACES their outer div rather than adding a
   *  wrapper inside it — a wrapper would put the pull header above the
   *  screen's padding, hard against the status bar. */
  className?: string;
  /** Re-fetch. Resolving ends the spinner; rejecting ends it too — the screen
   *  below already owns showing what went wrong, and a spinner left turning
   *  after a failed refresh is the one state worse than an error. */
  onRefresh: () => Promise<void>;
  children: ReactNode;
}): ReactNode {
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);
  // Where the finger went down, or null when this touch is not a pull.
  const start = useRef<number | null>(null);
  /**
   * How far it has come. **The gesture's own record, and what decides whether
   * a refresh fires** — `pull` above is the same number kept for painting, and
   * only for painting.
   *
   * They are not interchangeable. A React state value read inside touchend is
   * whatever the last render saw, and touchmove and touchend can both land
   * before a render does: a finger that lifts in the same frame as its last
   * move then ends a 100px pull with `pull` still 0, and the refresh silently
   * does not happen. It is intermittent by nature, which is the worst kind of
   * broken for a control whose whole job is to be the thing you fall back on.
   */
  const pulled = useRef(0);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  function onTouchStart(e: React.TouchEvent): void {
    // Not at the top, mid-refresh, or a two-finger gesture: not a pull.
    start.current =
      window.scrollY <= 0 && !busy && e.touches.length === 1 ? e.touches[0].clientY : null;
    pulled.current = 0;
  }

  function onTouchMove(e: React.TouchEvent): void {
    if (start.current === null) return;
    const dy = e.touches[0].clientY - start.current;
    // Pulling up is scrolling. Handing the gesture back rather than swallowing
    // it means a pull that starts at the top and turns into a scroll still
    // scrolls, which is what a finger that changes its mind expects.
    if (dy <= 0) {
      start.current = null;
      pulled.current = 0;
      setPull(0);
      return;
    }
    // Damped past the threshold: the first 72px track the finger 1:1 so the
    // gesture feels attached to it, and everything after that resists, which
    // is what says "this is as far as it goes" without a label.
    const damped = dy <= THRESHOLD_PX ? dy : THRESHOLD_PX + (dy - THRESHOLD_PX) * 0.35;
    pulled.current = Math.min(damped, MAX_PULL_PX);
    setPull(pulled.current);
  }

  function onTouchEnd(): void {
    const distance = pulled.current;
    start.current = null;
    pulled.current = 0;
    setPull(0);
    if (distance < THRESHOLD_PX || busy) return;
    setBusy(true);
    void onRefresh()
      .catch(() => undefined)
      .finally(() => {
        // The screen can be gone by now — a scout who pulls and immediately
        // opens a job unmounts this while the fetch is in flight.
        if (live.current) setBusy(false);
      });
  }

  const armed = pull >= THRESHOLD_PX;

  return (
    <div
      className={className ? `ptr ${className}` : "ptr"}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchEnd}
    >
      <div
        // `dragging` while a finger is on it, which is what turns the height
        // transition OFF. Measured at 14px into an 82px pull with the
        // transition left on: the header was easing towards the finger instead
        // of being held by it, which reads as lag rather than as a drag.
        className={`ptr-head${busy ? " busy" : ""}${pull > 0 && !busy ? " dragging" : ""}`}
        // Two states, one line of text, and no spinner asset: "keep pulling"
        // and "let go" are the only things the scout can act on, and the third
        // — "fetching" — is what the turning mark says.
        style={{ height: busy ? THRESHOLD_PX : pull }}
        aria-hidden={pull === 0 && !busy}
      >
        <span className="mark">{busy ? "↻" : armed ? "↑" : "↓"}</span>
        <span className="lbl">
          {t(lang, busy ? "refresh.working" : armed ? "refresh.release" : "refresh.pull")}
        </span>
      </div>
      {/* No transform on the content: the header above is in normal flow, so
          growing its height pushes the list down by exactly the pull. The
          list moving with the finger is what makes the gesture read as
          dragging the list rather than as a banner appearing over it. */}
      {children}
    </div>
  );
}
