import type { ReactNode } from "react";

import { useMe } from "@/hooks/useMe";

/**
 * Static tenant-name label, rendered between the AgriPulse wordmark
 * and the FarmSwitcher in the shell header. Pure context cue — not
 * clickable; users who can switch tenants still use the tenant tree
 * drawer (TenantIcon button on the right side of the header).
 *
 * If the user has multiple tenant memberships (rare — usually only
 * PlatformAdmin-with-grants), V1 shows the first one. A real "active
 * tenant" picker can layer on top of this later if needed.
 */
export function TenantBadge(): ReactNode {
  const { data: me } = useMe();
  const tenantName = me?.tenant_memberships[0]?.tenant_name;
  if (!tenantName) return null;
  return (
    <>
      <span
        className="truncate text-sm font-medium text-ap-ink"
        title={tenantName}
        aria-label="Active tenant"
      >
        {tenantName}
      </span>
      <span aria-hidden="true" className="text-ap-line">
        /
      </span>
    </>
  );
}
