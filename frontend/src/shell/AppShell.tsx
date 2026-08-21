import type { ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Header } from "./Header";
import { PlatformAlertBanner } from "./PlatformAlertBanner";
import { SideNav } from "./SideNav";

export function AppShell(): ReactNode {
  const { t } = useTranslation("common");
  // The Farm Console (and the legacy map) pin to the viewport and own their
  // internal scrolling. That's a shell-level concern — an inner element can't
  // opt its ancestors into `h-screen` — so it stays keyed off the pathname.
  //
  // Page *padding* is no longer decided here. <main> used to apply
  // `px-4 py-6`, which meant every page that added its own `p-6` double-padded
  // and every /settings/* page triple-padded. <Page> owns the inset now, so a
  // page's declared width is also its declared padding.
  const { pathname } = useLocation();
  const viewportPinned = pathname.startsWith("/labs/map");
  return (
    <div
      className={
        viewportPinned ? "flex h-screen flex-col bg-ap-bg" : "flex min-h-screen flex-col bg-ap-bg"
      }
    >
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:bg-white focus:px-3 focus:py-1 focus:text-sm focus:shadow-card"
      >
        {t("nav.skipToContent")}
      </a>
      {/* Above <Header> on purpose: a platform-wide failure outranks the
          page you are on, and this is the one strip that must not scroll
          away or sit inside a route that a tenant user never visits. */}
      <PlatformAlertBanner />
      <Header />
      <div className="flex min-h-0 w-full flex-1 gap-0">
        <SideNav />
        <main
          id="main-content"
          className={
            viewportPinned ? "min-w-0 flex-1 overflow-hidden" : "min-w-0 flex-1 overflow-x-hidden"
          }
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
