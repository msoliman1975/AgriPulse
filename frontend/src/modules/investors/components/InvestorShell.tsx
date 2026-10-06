import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { LanguageToggle } from "@/shell/LanguageToggle";
import { UserMenu } from "@/shell/UserMenu";

/**
 * The frame an Investor user gets in the web app: the product name, the
 * language switch and sign out. No side menu, no farm picker, no alerts — an
 * investor reads their own holdings and nothing else.
 */
export function InvestorShell(): ReactNode {
  return (
    <div className="flex min-h-screen flex-col bg-ap-bg">
      <header className="flex items-center justify-between border-b border-ap-line bg-ap-panel px-4 py-2">
        <span className="text-sm font-semibold text-ap-primary">AgriPulse</span>
        <div className="flex items-center gap-3">
          <LanguageToggle />
          <UserMenu />
        </div>
      </header>
      <main id="main-content" className="flex-1">
        <RouteErrorBoundary>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  );
}
