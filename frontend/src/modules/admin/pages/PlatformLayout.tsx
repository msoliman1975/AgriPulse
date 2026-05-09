import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { PlatformAdminGuard } from "@/auth/PlatformAdminGuard";

/**
 * `/platform/*` layout. The guard is mounted here so every nested route
 * inherits the capability check without each page re-asserting it.
 *
 * Renamed from AdminLayout (PR-Reorg2). The /admin/* paths still
 * resolve via redirects in App.tsx for back-compat.
 */
export function PlatformLayout(): ReactNode {
  return (
    <PlatformAdminGuard>
      <Outlet />
    </PlatformAdminGuard>
  );
}
