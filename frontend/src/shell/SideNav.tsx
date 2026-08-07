import clsx from "clsx";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useLocation, useParams } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

import {
  AlertsIcon,
  GearIcon,
  InsightsIcon,
  LandUnitsIcon,
  PanelToggleIcon,
  PlanIcon,
  RecommendationsIcon,
  ReportsIcon,
  SignalsIcon,
  TenantIcon,
  UsersIcon,
} from "./icons";

const COLLAPSE_STORAGE_KEY = "ap.sidenav.collapsed";

function readCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    /* storage may be disabled — default to the expanded nav */
    return false;
  }
}

/** Collapsed/expanded is a per-browser preference, not per-farm or per-route. */
function useCollapsed(): readonly [boolean, () => void] {
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      /* storage may be disabled; the choice still applies for this session */
    }
  }, [collapsed]);
  const toggle = useCallback(() => setCollapsed((value) => !value), []);
  return [collapsed, toggle] as const;
}

interface SideNavItemProps {
  to: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  activePathPrefix?: string;
  badge?: string;
  collapsed?: boolean;
}

function SideNavItem({
  to,
  label,
  icon,
  disabled,
  activePathPrefix,
  badge,
  collapsed = false,
}: SideNavItemProps): ReactNode {
  const location = useLocation();
  const { t } = useTranslation("common");
  // Collapsed rows carry the label in the native tooltip and keep it in the
  // accessibility tree via .sr-only, so screen readers read the same nav.
  const layout = collapsed ? "justify-center px-0" : "gap-2 px-3";
  const text = collapsed ? <span className="sr-only">{label}</span> : <span>{label}</span>;
  if (disabled) {
    const hint = t("workspaceNav.pickFarm");
    return (
      <span
        aria-disabled="true"
        title={collapsed ? `${label} — ${hint}` : hint}
        className={clsx("flex items-center rounded-md py-2 text-sm text-ap-muted/60", layout)}
      >
        {icon}
        {text}
        {badge && !collapsed ? <BetaBadge>{badge}</BetaBadge> : null}
      </span>
    );
  }
  return (
    <NavLink
      to={to}
      title={collapsed ? label : undefined}
      className={() => {
        const isActive = activePathPrefix
          ? location.pathname.startsWith(activePathPrefix)
          : location.pathname === to;
        return clsx(
          "flex items-center rounded-md py-2 text-sm transition-colors",
          layout,
          isActive
            ? "bg-ap-primary-soft font-medium text-ap-primary"
            : "text-ap-ink hover:bg-ap-line/50",
        );
      }}
    >
      {icon}
      {text}
      {badge && !collapsed ? <BetaBadge>{badge}</BetaBadge> : null}
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

interface NavShellProps {
  heading: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/**
 * The nav chrome shared by both personas: fixed rail width, group heading and
 * the collapse toggle. Collapsed drops to an icons-only rail (`w-14`); the
 * group heading goes with the labels since there's nothing left to head.
 */
function NavShell({ heading, collapsed, onToggle, children }: NavShellProps): ReactNode {
  const { t } = useTranslation("common");
  const toggleLabel = collapsed ? t("workspaceNav.expand") : t("workspaceNav.collapse");
  return (
    <nav
      aria-label="Primary"
      className={clsx(
        "hidden flex-shrink-0 flex-col overflow-y-auto border-e border-ap-line bg-ap-panel py-3 transition-[width] duration-150 md:flex",
        collapsed ? "w-14" : "w-56",
      )}
    >
      <div className={clsx("flex items-center pb-1 pt-3", collapsed ? "px-2" : "px-3")}>
        {collapsed ? null : (
          <span className="text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
            {heading}
          </span>
        )}
        <button
          type="button"
          onClick={onToggle}
          title={toggleLabel}
          aria-label={toggleLabel}
          aria-expanded={!collapsed}
          className={clsx(
            "rounded-md p-1 text-ap-muted transition-colors hover:bg-ap-line/50 hover:text-ap-ink",
            collapsed ? "mx-auto" : "-me-1 ms-auto",
          )}
        >
          <PanelToggleIcon className="h-4 w-4 rtl:-scale-x-100" collapsed={collapsed} />
        </button>
      </div>
      <div className="flex flex-col gap-0.5 px-2">{children}</div>
    </nav>
  );
}

export function SideNav(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  const hasFarm = Boolean(farmId);
  const isPlatformAdmin = useCapability("platform.manage_tenants");
  const { t } = useTranslation(["admin", "common"]);
  const [collapsed, toggleCollapsed] = useCollapsed();
  const farmSegment = farmId ?? "";

  // Persona separation (portal-restructure Q8): PlatformAdmin sees
  // ONLY the Platform Management Portal nav. Tenant users see the
  // AgriPulse workspace + per-farm config + tenant Settings hub.
  if (isPlatformAdmin) {
    return (
      <NavShell heading={t("nav.section")} collapsed={collapsed} onToggle={toggleCollapsed}>
        <SideNavItem
          to="/platform/tenants"
          label={t("nav.tenants")}
          icon={<TenantIcon className="h-4 w-4" />}
          activePathPrefix="/platform/tenants"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/defaults"
          label={t("nav.defaults")}
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/platform/defaults"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/crops"
          label={t("nav.crops")}
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/platform/crops"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/plan-templates"
          label={t("nav.planTemplates")}
          icon={<PlanIcon className="h-4 w-4" />}
          activePathPrefix="/platform/plan-templates"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/backfill"
          label={t("nav.backfill")}
          icon={<PlanIcon className="h-4 w-4" />}
          activePathPrefix="/platform/backfill"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/observer"
          label={t("nav.observer")}
          icon={<AlertsIcon className="h-4 w-4" />}
          activePathPrefix="/platform/observer"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/admins"
          label={t("nav.platformAdmins")}
          icon={<UsersIcon className="h-4 w-4" />}
          activePathPrefix="/platform/admins"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/integrations/health"
          label={t("nav.platformHealth")}
          icon={<AlertsIcon className="h-4 w-4" />}
          activePathPrefix="/platform/integrations/health"
          collapsed={collapsed}
        />
      </NavShell>
    );
  }

  // Workspace items resolve their `:farmId` from the URL. When no farm
  // is active (e.g. on the org-admin overview at /farms), they render
  // disabled so clicking won't 404.
  return (
    // Single workspace list. Per-farm + tenant configuration (Imagery &
    // weather, Custom signals, Settings hub) moved to the top-bar Configs
    // menu, so the left nav is purely the operational surfaces.
    <NavShell
      heading={t("common:workspaceNav.workspace")}
      collapsed={collapsed}
      onToggle={toggleCollapsed}
    >
      <SideNavItem
        to={hasFarm ? `/insights/${farmSegment}` : "#"}
        label={t("common:workspaceNav.insights")}
        icon={<InsightsIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/insights/"
        collapsed={collapsed}
      />
      <SideNavItem
        to={hasFarm ? `/labs/map/${farmSegment}` : "/labs/map"}
        label={t("common:workspaceNav.farmManagement")}
        icon={<LandUnitsIcon className="h-4 w-4" />}
        activePathPrefix={hasFarm ? `/labs/map/${farmSegment}` : "/labs/map"}
        collapsed={collapsed}
      />
      {/* /labs/map is the single Farm-management surface in nav. The
          legacy map experience (/labs/map-legacy) is delisted but still
          routed — the new console's "Edit AoI" deep-links into it until
          AoI/polygon editing reaches parity there. TODO(nuke-legacy-farms):
          drop /labs/map-legacy + /farms/* routes once AoI-edit lands in
          the console. */}
      <SideNavItem
        to={hasFarm ? `/board/${farmSegment}` : "#"}
        label={t("common:workspaceNav.plan")}
        icon={<PlanIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/board/"
        collapsed={collapsed}
      />
      <SideNavItem
        to={hasFarm ? `/signals/${farmSegment}` : "#"}
        label={t("common:workspaceNav.signals")}
        icon={<SignalsIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/signals/"
        collapsed={collapsed}
      />
      <SideNavItem
        to={hasFarm ? `/recommendations/${farmSegment}` : "#"}
        label={t("common:workspaceNav.recommendations")}
        icon={<RecommendationsIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/recommendations/"
        collapsed={collapsed}
      />
      <SideNavItem
        to={hasFarm ? `/alerts/${farmSegment}` : "#"}
        label={t("common:workspaceNav.alerts")}
        icon={<AlertsIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/alerts/"
        collapsed={collapsed}
      />
      <SideNavItem
        to={hasFarm ? `/reports/${farmSegment}` : "#"}
        label={t("common:workspaceNav.reports")}
        icon={<ReportsIcon className="h-4 w-4" />}
        disabled={!hasFarm}
        activePathPrefix="/reports/"
        collapsed={collapsed}
      />
    </NavShell>
  );
}
