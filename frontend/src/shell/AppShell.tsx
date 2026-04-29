import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Header } from "./Header";
import { SideNav } from "./SideNav";

export function AppShell(): ReactNode {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-h-screen flex-col bg-sand-50">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:bg-white focus:px-3 focus:py-1 focus:text-sm focus:shadow-card"
      >
        {t("nav.skipToContent")}
      </a>
      <Header />
      <div className="mx-auto flex w-full max-w-7xl flex-1 gap-6 px-4 py-6">
        <SideNav />
        <main id="main-content" className="flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
