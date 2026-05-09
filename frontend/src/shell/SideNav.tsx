import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useLocation, useParams } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

import {
  AlertsIcon,
  GearIcon,
  ImageryIcon,
  InsightsIcon,
  LandUnitsIcon,
  PlanIcon,
  RecommendationsIcon,
  ReportsIcon,
  SignalsIcon,
  TenantIcon,
} from "./icons";

interface SideNavItemProps {
  to: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  activePathPrefix?: string;
}

function SideNavItem({
  to,
  label,
  icon,
  disabled,
  activePathPrefix,
}: SideNavItemProps): ReactNode {
  const location = useLocation();
  if (disabled) {
    return (
      <span
        aria-disabled="true"
        title="Pick a farm to continue"
        className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-ap-muted/60"
      >
        {icon}
        <span>{label}</span>
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
    </NavLink>
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
  const { t } = useTranslation("admin");
  // Workspace items resolve their `:farmId` from the URL. When no farm
  // is active (e.g. on the org-admin overview at /farms), they render
  // disabled so clicking won't 404.
  const farmSegment = farmId ?? "";
  return (
    <nav
      aria-label="Primary"
      className="hidden w-56 flex-shrink-0 overflow-y-auto border-e border-ap-line bg-ap-panel py-3 md:block"
    >
      <GroupHeader>Workspace</GroupHeader>
      <div className="flex flex-col gap-0.5 px-2">
        <SideNavItem
          to={hasFarm ? `/insights/${farmSegment}` : "#"}
          label="Insights"
          icon={<InsightsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/insights/"
        />
        <SideNavItem
          to={hasFarm ? `/farms/${farmSegment}` : "/farms"}
          label="Land units"
          icon={<LandUnitsIcon className="h-4 w-4" />}
          activePathPrefix={hasFarm ? `/farms/${farmSegment}` : "/farms"}
        />
        <SideNavItem
          to={hasFarm ? `/alerts/${farmSegment}` : "#"}
          label="Alerts"
          icon={<AlertsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/alerts/"
        />
        <SideNavItem
          to={hasFarm ? `/recommendations/${farmSegment}` : "#"}
          label="Recommendations"
          icon={<RecommendationsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/recommendations/"
        />
        <SideNavItem
          to={hasFarm ? `/signals/${farmSegment}` : "#"}
          label="Signals"
          icon={<SignalsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/signals/"
        />
        <SideNavItem
          to={hasFarm ? `/plan/${farmSegment}` : "#"}
          label="Plan"
          icon={<PlanIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/plan/"
        />
        <SideNavItem
          to={hasFarm ? `/reports/${farmSegment}` : "#"}
          label="Reports"
          icon={<ReportsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/reports/"
        />
      </div>
      {/* Per-farm configuration that genuinely needs a farm context. The
          tenant-wide config (rules, users, decision trees) lives under
          the Settings hub so a farm doesn't have to be active. */}
      <GroupHeader>Configuration</GroupHeader>
      <div className="flex flex-col gap-0.5 px-2">
        <SideNavItem
          to={hasFarm ? `/config/imagery/${farmSegment}` : "#"}
          label="Imagery & weather"
          icon={<ImageryIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/config/imagery/"
        />
        <SideNavItem
          to={hasFarm ? `/config/signals/${farmSegment}` : "#"}
          label="Custom signals"
          icon={<SignalsIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/config/signals/"
        />
        <SideNavItem
          to="/settings"
          label="Settings"
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/settings"
        />
      </div>
      {isPlatformAdmin && (
        <>
          <GroupHeader>{t("nav.section")}</GroupHeader>
          <div className="flex flex-col gap-0.5 px-2">
            <SideNavItem
              to="/admin/tenants"
              label={t("nav.tenants")}
              icon={<TenantIcon className="h-4 w-4" />}
              activePathPrefix="/admin/tenants"
            />
          </div>
        </>
      )}
    </nav>
  );
}
