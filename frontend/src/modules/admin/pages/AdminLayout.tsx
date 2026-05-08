import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { PlatformAdminGuard } from "@/auth/PlatformAdminGuard";

/**
 * `/admin/*` layout. The guard is mounted here so every nested route
 * inherits the capability check without each page re-asserting it.
 */
export function AdminLayout(): ReactNode {
  return (
    <PlatformAdminGuard>
      <Outlet />
    </PlatformAdminGuard>
  );
}
