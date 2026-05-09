import type { ReactNode } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

/**
 * Inverse of `PlatformAdminGuard`. Used as a layout route element
 * around the Agri.Pulse tree. Redirects PlatformAdmin /
 * PlatformSupport callers to /platform — the persona-separation
 * rule: Platform staff stay in /platform, tenant users stay in /.
 *
 * Tenant users (no platform role) pass through and the nested
 * Outlet renders the actual page.
 */
export function AgriPulseGuard(): ReactNode {
  const isPlatformStaff = useCapability("platform.manage_tenants");
  if (isPlatformStaff) {
    return <Navigate to="/platform" replace />;
  }
  return <Outlet />;
}
