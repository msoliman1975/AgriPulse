import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useLocation, useParams } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

import {
  AlertsIcon,
  GearIcon,
  InsightsIcon,
  LandUnitsIcon,
  PlanIcon,
  RecommendationsIcon,
  ReportsIcon,
  SignalsIcon,
  TenantIcon,
  UsersIcon,
} from "./icons";

interface SideNavItemProps {
  to: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  activePathPrefix?: string;
  badge?: string;
}

function SideNavItem({
  to,
  label,
  icon,
  disabled,
  activePathPrefix,
  badge,
}: SideNavItemProps): ReactNode {
  const location = useLocation();
  const { t } = useTranslation("common");
  if (disabled) {
    return (
      <span
        aria-disabled="true"
        title={t("workspaceNav.pickFarm")}
        className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-ap-muted/60"
      >
        {icon}
        <span>{label}</span>
        {badge ? <BetaBadge>{badge}</BetaBadge> : null}
      </span>
    );
  }
  return (
    <NavLink
      to={to}
      className={() => {
        const isActive = activePathPrefix
          ? location.pathname.startsWith(activePathPrefix)
          : location.pathname === to;
        return clsx(
          "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
          isActive
            ? "bg-ap-primary-soft font-medium text-ap-primary"
            : "text-ap-ink hover:bg-ap-line/50",
        );
      }}
    >
      {icon}
      <span>{label}</span>
      {badge ? <BetaBadge>{badge}</BetaBadge> : null}
    </NavLink>
  );
}

function BetaBadge({ children }: { children: string }): ReactNode {
  return (
    <span className="ms-auto rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-800">
      {children}
    </span>
  );
}

function GroupHeader({ children }: { children: string }): ReactNode {
  return (
    <div className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
      {children}
    </div>
  );
}

export function SideNav(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  const hasFarm = Boolean(farmId);
  const isPlatformAdmin = useCapability("platform.manage_tenants");
  const { t } = useTranslation(["admin", "common"]);
  const farmSegment = farmId ?? "";

  // Persona separation (portal-restructure Q8): PlatformAdmin sees
  // ONLY the Platform Management Portal nav. Tenant users see the
  // AgriPulse workspace + per-farm config + tenant Settings hub.
  if (isPlatformAdmin) {
    return (
      <nav
        aria-label="Primary"
        className="hidden w-56 flex-shrink-0 overflow-y-auto border-e border-ap-line bg-ap-panel py-3 md:block"
      >
        <GroupHeader>{t("nav.section")}</GroupHeader>
        <div className="flex flex-col gap-0.5 px-2">
          <SideNavItem
            to="/platform/tenants"
            label={t("nav.tenants")}
            icon={<TenantIcon className="h-4 w-4" />}
            activePathPrefix="/platform/tenants"
          />
          <SideNavItem
            to="/platform/defaults"
            label={t("nav.defaults")}
            icon={<GearIcon className="h-4 w-4" />}
            activePathPrefix="/platform/defaults"
          />
          <SideNavItem
            to="/platform/admins"
            label={t("nav.platformAdmins")}
            icon={<UsersIcon className="h-4 w-4" />}
            activePathPrefix="/platform/admins"
          />
          <SideNavItem
            to="/platform/integrations/health"
            label={t("nav.platformHealth")}
            icon={<AlertsIcon className="h-4 w-4" />}
            activePathPrefix="/platform/integrations/health"
          />
        </div>
      </nav>
    );
  }

  // Workspace items resolve their `:farmId` from the URL. When no farm
  // is active (e.g. on the org-admin overview at /farms), they render
  // disabled so clicking won't 404.
  return (
    <nav
      aria-label="Primary"
      className="hidden w-56 flex-shrink-0 overflow-y-auto border-e border-ap-line bg-ap-panel py-3 md:block"
    >
      {/* Single workspace list. Per-farm + tenant configuration (Imagery &
          weather, Custom signals, Settings hub) moved to the top-bar Configs
          menu, so the left nav is purely the operational surfaces. */}
      <GroupHeader>{t("common:workspaceNav.workspace")}</GroupHeader>
      <div className="flex flex-col gap-0.5 px-2">
        <SideNavItem
          to={hasFarm ? `/insights/${farmSegment}` : "#"}
          label={t("common:workspaceNav.insights")}
          icon={<InsightsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/insights/"
        />
        <SideNavItem
          to={hasFarm ? `/labs/map/${farmSegment}` : "/labs/map"}
          label={t("common:workspaceNav.farmManagement")}
          icon={<LandUnitsIcon className="h-4 w-4" />}
          activePathPrefix={hasFarm ? `/labs/map/${farmSegment}` : "/labs/map"}
        />
        {/* TODO(nuke-legacy-farms): /labs/map is the single Farm-management
            surface; the legacy /farms form view stays routed as a fallback
            until /labs/map reaches parity. */}
        <SideNavItem
          to={hasFarm ? `/board/${farmSegment}` : "#"}
          label={t("common:workspaceNav.plan")}
          icon={<PlanIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/board/"
        />
        <SideNavItem
          to={hasFarm ? `/signals/${farmSegment}` : "#"}
          label={t("common:workspaceNav.signals")}
          icon={<SignalsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/signals/"
        />
        <SideNavItem
          to={hasFarm ? `/recommendations/${farmSegment}` : "#"}
          label={t("common:workspaceNav.recommendations")}
          icon={<RecommendationsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/recommendations/"
        />
        <SideNavItem
          to={hasFarm ? `/alerts/${farmSegment}` : "#"}
          label={t("common:workspaceNav.alerts")}
          icon={<AlertsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/alerts/"
        />
        <SideNavItem
          to={hasFarm ? `/reports/${farmSegment}` : "#"}
          label={t("common:workspaceNav.reports")}
          icon={<ReportsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/reports/"
        />
      </div>
    </nav>
  );
}
