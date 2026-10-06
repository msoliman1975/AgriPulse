import clsx from "clsx";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useLocation, useParams } from "react-router-dom";

import { useCapability, useClaims } from "@/rbac/useCapability";

import {
  BlockIcon,
  InvestmentsIcon,
  AlertsIcon,
  GearIcon,
  InsightsIcon,
  LandUnitsIcon,
  PanelToggleIcon,
  PlanIcon,
  RecommendationsIcon,
  ReportsIcon,
  RulesIcon,
  SignalsIcon,
  HealthIcon,
  TimelineIcon,
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
  // Collapsed hides the badge, so a badged row would otherwise be
  // indistinguishable from its unbadged twin — two links both named
  // "Farm Management". Fold the badge into the accessible name instead.
  const srLabel = badge ? `${label} (${badge})` : label;
  const text = collapsed ? <span className="sr-only">{srLabel}</span> : <span>{label}</span>;
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

/**
 * A second group heading inside one NavShell, for the Investments group.
 * Collapsed, the heading becomes a thin rule so the two groups stay apart.
 */
function NavGroupHeading({ label, collapsed }: { label: string; collapsed: boolean }): ReactNode {
  if (collapsed) return <div role="separator" className="mx-2 my-2 border-t border-ap-line" />;
  return (
    <div className="px-1 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
      {label}
    </div>
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
  const { t: ti } = useTranslation("investors");
  const [collapsed, toggleCollapsed] = useCollapsed();
  const farmSegment = farmId ?? "";
  // Farm work and Investments are separate areas. A user who cannot read a
  // farm plan (an Investment Manager) sees no Workspace group at all, and a
  // farm role sees no Investments group.
  // A farm-scoped user holds plan.read only on their farms, so the tenant
  // check alone would hide Workspace whenever no farm is in the URL.
  const claims = useClaims();
  const tenantFarmWork = useCapability("plan.read");
  const canHoldings = useCapability("holding.read");
  const canInvestors = useCapability("investor.read");
  const canInvestments = canHoldings || canInvestors;
  // Workspace stays for everyone except an investments-only user, so a role
  // with neither (e.g. Billing Admin) keeps the menu it had.
  const showWorkspace = tenantFarmWork || (claims?.farm_scopes?.length ?? 0) > 0 || !canInvestments;

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
        {/* The platform default of the block health rule. Crop paths change
            single values on the catalog's Health tab. */}
        <SideNavItem
          to="/platform/health-definition"
          label={t("nav.healthDefinition")}
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/platform/health-definition"
          collapsed={collapsed}
        />
        {/* /platform/catalog is the one crop row in the nav. The older
            /platform/crops tree is delisted but still routed: the catalog's
            attribute panel deep-links to /platform/crops/:id/attributes,
            which is where attribute definitions are still authored.
            TODO: delist that too once attribute authoring moves into the
            catalog inspector, then delete /platform/crops. */}
        <SideNavItem
          to="/platform/catalog"
          label={t("nav.catalog")}
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/platform/catalog"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/signals"
          label={t("nav.platformSignals")}
          icon={<GearIcon className="h-4 w-4" />}
          activePathPrefix="/platform/signals"
          collapsed={collapsed}
        />
        {/* The 33 platform trees are database rows now (public migration
            0085), so this is where they are edited. A tenant admin sees the
            same pages at /decision-trees for their own trees and cannot edit
            these; the API enforces both halves. */}
        <SideNavItem
          to="/platform/decision-trees"
          label={t("nav.platformDecisionTrees")}
          icon={<RulesIcon className="h-4 w-4" />}
          activePathPrefix="/platform/decision-trees"
          collapsed={collapsed}
        />
        {/* The beta designer, a separate surface beside the current editor
            while the folding engine is built. */}
        <SideNavItem
          to="/platform/decision-trees-beta"
          label={t("nav.platformDecisionTreesBeta")}
          icon={<RulesIcon className="h-4 w-4" />}
          activePathPrefix="/platform/decision-trees-beta"
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
          to="/platform/roles"
          label={t("nav.roles")}
          icon={<RulesIcon className="h-4 w-4" />}
          activePathPrefix="/platform/roles"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/usage"
          label={t("nav.usage")}
          icon={<PlanIcon className="h-4 w-4" />}
          activePathPrefix="/platform/usage"
          collapsed={collapsed}
        />
        <SideNavItem
          to="/platform/alerts"
          label={t("nav.platformAlerts")}
          icon={<AlertsIcon className="h-4 w-4" />}
          activePathPrefix="/platform/alerts"
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
      heading={showWorkspace ? t("common:workspaceNav.workspace") : ti("nav.group")}
      collapsed={collapsed}
      onToggle={toggleCollapsed}
    >
      {showWorkspace ? (
        <>
          <SideNavItem
            to={hasFarm ? `/insights/${farmSegment}` : "#"}
            label={t("common:workspaceNav.insights")}
            icon={<InsightsIcon className="h-4 w-4" />}
            disabled={!hasFarm}
            activePathPrefix="/insights/"
            collapsed={collapsed}
          />
          {/* Farm Console v2 (/labs/map-v2) is the one Farm-management row in the
          nav. It carried a BETA badge while it ran beside the older console
          at /labs/map; the badge went with the second row, since "beta" says
          nothing to a user who has no other console to choose.

          Two older surfaces stay routed but delisted:
            * /labs/map      — the previous console. Nothing links to it now.
            * /labs/map-legacy — the original map. The console's "Edit AoI"
              still deep-links into it until AoI/polygon editing reaches
              parity in the console.
          TODO(nuke-legacy-farms): delete /labs/map, /labs/map-legacy and
          /farms/* once AoI-edit lands in the console. */}
          <SideNavItem
            to={hasFarm ? `/labs/map-v2/${farmSegment}` : "/labs/map-v2"}
            label={t("common:workspaceNav.farmManagement")}
            icon={<LandUnitsIcon className="h-4 w-4" />}
            activePathPrefix={hasFarm ? `/labs/map-v2/${farmSegment}` : undefined}
            collapsed={collapsed}
          />
          <SideNavItem
            to={hasFarm ? `/board/${farmSegment}` : "#"}
            label={t("common:workspaceNav.plan")}
            icon={<PlanIcon className="h-4 w-4" />}
            disabled={!hasFarm}
            activePathPrefix="/board/"
            collapsed={collapsed}
          />
          {/* The replay surface. Sits after Plan because it is read-only
          history — you plan forward here and look backward there. */}
          <SideNavItem
            to={hasFarm ? `/timeline/${farmSegment}` : "#"}
            label={t("common:workspaceNav.timeline")}
            icon={<TimelineIcon className="h-4 w-4" />}
            disabled={!hasFarm}
            activePathPrefix="/timeline/"
            collapsed={collapsed}
          />
          {/* Farm Health View. Next to the replay because both are read-only
          history; this one answers "what does the tree say", the other
          "what happened". */}
          <SideNavItem
            to={hasFarm ? `/farm-health/${farmSegment}` : "#"}
            label={t("common:workspaceNav.farmHealth")}
            icon={<HealthIcon className="h-4 w-4" />}
            disabled={!hasFarm}
            activePathPrefix="/farm-health/"
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
          {/* The one queue over recommendations and alerts. /recommendations and
          /alerts are delisted: everything they did is here — acknowledge,
          resolve, apply, dismiss, defer, the four-horizon guidance and the
          decision path — and this screen also filters, groups and dispatches.
          Both stay routed, because notification links point at them.
          TODO: repoint those links, then delete the two pages. */}
          <SideNavItem
            to={hasFarm ? `/action-center/${farmSegment}` : "#"}
            label={t("common:workspaceNav.actionCenter")}
            icon={<RecommendationsIcon className="h-4 w-4" />}
            disabled={!hasFarm}
            activePathPrefix="/action-center/"
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
        </>
      ) : null}
      {canInvestments ? (
        <>
          {showWorkspace ? <NavGroupHeading label={ti("nav.group")} collapsed={collapsed} /> : null}
          {canHoldings ? (
            <SideNavItem
              to="/investments"
              label={ti("nav.overview")}
              icon={<InvestmentsIcon className="h-4 w-4" />}
              collapsed={collapsed}
            />
          ) : null}
          {canHoldings ? (
            <SideNavItem
              to="/investments/holdings"
              label={ti("nav.holdings")}
              icon={<BlockIcon className="h-4 w-4" />}
              activePathPrefix="/investments/holdings"
              collapsed={collapsed}
            />
          ) : null}
          {canInvestors ? (
            <SideNavItem
              to="/investments/investors"
              label={ti("nav.investors")}
              icon={<UsersIcon className="h-4 w-4" />}
              activePathPrefix="/investments/investors"
              collapsed={collapsed}
            />
          ) : null}
        </>
      ) : null}
    </NavShell>
  );
}
