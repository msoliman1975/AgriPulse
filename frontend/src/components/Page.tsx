import clsx from "clsx";
import type { ReactNode } from "react";

export type PageWidth = "wide" | "standard" | "full" | "bleed";

interface PageProps {
  /**
   * The content frame. `wide` is the default — see
   * docs/proposals/ui-standard-implementation-plan.md decision 5.
   *
   *   wide      max-w-6xl — index, detail, settings, dashboards
   *   standard  max-w-5xl — escape hatch for sparse tables and forms
   *   full      uncapped  — board, wide canvases
   *   bleed     uncapped, unpadded — map surfaces that own their scrolling
   */
  width?: PageWidth;
  children: ReactNode;
  className?: string;
}

/*
 * The one page frame.
 *
 * Before this, 9 wrapper variants coexisted (`space-y-4`, `space-y-6`,
 * `mx-auto max-w-5xl p-6`, `flex-col gap-6`, …) and two of them were bugs:
 * `AppShell` already applied `px-4 py-6`, so any page adding its own `p-6`
 * double-padded, and `/settings/*` triple-padded because `SettingsLayout`
 * added a third layer.
 *
 * The fix inverts ownership: `AppShell`'s <main> carries NO padding and
 * <Page> owns the horizontal inset, the max-width, and the vertical rhythm.
 * That makes `bleed` expressible (it simply omits the padding) instead of
 * needing the shell to special-case routes by pathname.
 */
const WIDTH_CLASS: Record<PageWidth, string> = {
  wide: "mx-auto w-full max-w-6xl px-4 py-6",
  standard: "mx-auto w-full max-w-5xl px-4 py-6",
  full: "w-full px-4 py-6",
  bleed: "h-full w-full",
};

export function Page({ width = "wide", children, className }: PageProps): ReactNode {
  return (
    <div
      className={clsx(
        WIDTH_CLASS[width],
        // Bleed surfaces own their internal layout entirely.
        width === "bleed" ? "flex flex-col" : "flex flex-col gap-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
