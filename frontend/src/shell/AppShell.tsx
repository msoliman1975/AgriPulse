import type { ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Header } from "./Header";
import { SideNav } from "./SideNav";

export function AppShell(): ReactNode {
  const { t } = useTranslation("common");
  // The Farm Console (and the legacy map) are full-bleed map surfaces: no page
  // padding, and they own their internal scrolling. Every other page keeps the
  // standard padded content area.
  const { pathname } = useLocation();
  const fullBleed = pathname.startsWith("/labs/map");
  return (
    <div className={fullBleed ? "flex h-screen flex-col bg-ap-bg" : "flex min-h-screen flex-col bg-ap-bg"}>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:bg-white focus:px-3 focus:py-1 focus:text-sm focus:shadow-card"
      >
        {t("nav.skipToContent")}
      </a>
      <Header />
      <div className="flex w-full min-h-0 flex-1 gap-0">
        <SideNav />
        <main
          id="main-content"
          className={fullBleed ? "min-w-0 flex-1 overflow-hidden" : "flex-1 overflow-x-hidden px-4 py-6"}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
