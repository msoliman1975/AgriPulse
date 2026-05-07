import clsx from "clsx";
import type { ReactNode } from "react";
import { NavLink, useLocation, useParams } from "react-router-dom";

import {
  AlertsIcon,
  ImageryIcon,
  InsightsIcon,
  LandUnitsIcon,
  PlanIcon,
  ReportsIcon,
  RulesIcon,
  UsersIcon,
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
      <GroupHeader>Configuration</GroupHeader>
      <div className="flex flex-col gap-0.5 px-2">
        <SideNavItem
          to={hasFarm ? `/config/rules/${farmSegment}` : "#"}
          label="Rules & thresholds"
          icon={<RulesIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/config/rules/"
        />
        <SideNavItem
          to={hasFarm ? `/config/imagery/${farmSegment}` : "#"}
          label="Imagery & weather"
          icon={<ImageryIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/config/imagery/"
        />
        <SideNavItem
          to={hasFarm ? `/config/users/${farmSegment}` : "#"}
          label="Users & roles"
          icon={<UsersIcon className="h-4 w-4" />}
          disabled={!hasFarm}
          activePathPrefix="/config/users/"
        />
      </div>
    </nav>
  );
}
