import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useCapability, useClaims } from "@/rbac/useCapability";

/**
 * Inverse of `PlatformAdminGuard`. Used as a layout route element
 * around the AgriPulse tree. Redirects PlatformAdmin /
 * PlatformSupport callers to /platform â€” the persona-separation
 * rule: Platform staff stay in /platform, tenant users stay in /.
 *
 * Tenant users (no platform role) pass through and the nested
 * Outlet renders the actual page.
 */
export function AgriPulseGuard(): ReactNode {
  const isPlatformStaff = useCapability("platform.manage_tenants");
  const isInvestor = useCapability("investor_app.use");
  const canFarmWork = useCapability("plan.read");
  const canHoldings = useCapability("holding.read");
  const claims = useClaims();
  const { pathname } = useLocation();
  if (isPlatformStaff) {
    return <Navigate to="/platform" replace />;
  }
  // An Investor reads only their own holdings; every staff page is closed.
  if (isInvestor) {
    return <Navigate to="/my-holdings" replace />;
  }
  // An Investment Manager has no farm work; the home page is Investments.
  const investmentsOnly = canHoldings && !canFarmWork && (claims?.farm_scopes?.length ?? 0) === 0;
  if (investmentsOnly && pathname === "/") {
    return <Navigate to="/investments" replace />;
  }
  return <Outlet />;
}
