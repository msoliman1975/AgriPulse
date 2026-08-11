import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import type { RbacCapability, RbacRole } from "@/api/rbacMatrix";
import { DataTable, type Column } from "@/components/DataTable";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Tooltip } from "@/components/Tooltip";
import { Toolbar, ToolbarChips, type FilterAxis, type FilterValues } from "@/components/Toolbar";
import { mapAsyncState, queryState } from "@/components/asyncState";
import { useRbacMatrix } from "@/queries/rbacMatrix";

type ViewMode = "byRole" | "byCapability";

/** Order the tier bands the way authority flows, not alphabetically. */
const TIER_ORDER = ["platform", "tenant", "farm"] as const;

/**
 * A column header that explains itself on hover/focus.
 *
 * "Granted", "Scope" and "Status" are all terms of art here — Scope in
 * particular is documentation only (the resolver ignores it), which nobody
 * would guess. The description is also rendered sr-only, because the shared
 * Tooltip is visual and does not wire aria-describedby.
 */
function HeaderWithHint({ label, hint }: { label: string; hint: string }): ReactNode {
  return (
    <Tooltip content={hint} className="w-56 whitespace-normal text-start font-normal">
      {/* A real button: it is focusable by keyboard and reveals the hint, which
          a bare span with tabIndex is not. */}
      <button
        type="button"
        className="cursor-help font-inherit underline decoration-dotted underline-offset-4"
      >
        {label}
        <span className="sr-only"> — {hint}</span>
      </button>
    </Tooltip>
  );
}

export function PlatformRolesPage(): ReactNode {
  const { t } = useTranslation("admin");
  const matrix = useRbacMatrix();

  // Selection lives in the URL so a view can be handed to someone else,
  // matching the pattern PlatformObserverPage established.
  const [params] = useSearchParams();
  const selectedRole = params.get("role");

  const [view, setView] = useState<ViewMode>("byRole");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<FilterValues>({});
  // Default to "granted only": it turns the first paint into the 20-80 rows
  // that answer "what can this role do?" instead of all 94.
  const [granted, setGranted] = useState<string | null>("granted");

  const data = matrix.data;
  const roles = useMemo(() => data?.roles ?? [], [data]);
  const capabilities = useMemo(() => data?.capabilities ?? [], [data]);

  // Falls back to the first role once loaded, so the detail table is never an
  // empty frame waiting on a click.
  const activeRole: RbacRole | undefined =
    roles.find((r) => r.name === selectedRole) ?? roles[0];

  const grantedNames = useMemo(
    () => new Set(activeRole?.capabilities ?? []),
    [activeRole],
  );

  /** capability name -> the roles granting it, for the by-capability view. */
  const grantedBy = useMemo(() => {
    const map = new Map<string, RbacRole[]>();
    for (const cap of capabilities) map.set(cap.name, []);
    for (const role of roles) {
      for (const name of role.capabilities) map.get(name)?.push(role);
    }
    return map;
  }, [capabilities, roles]);

  const axes: readonly FilterAxis[] = useMemo(() => {
    const resources = Array.from(new Set(capabilities.map((c) => c.resource))).sort();
    return [
      {
        key: "scope",
        label: t("roles.filterScope"),
        options: TIER_ORDER.map((s) => ({ value: s, label: t(`roles.tier_${s}`) })),
      },
      {
        key: "resource",
        label: t("roles.filterResource"),
        options: resources.map((r) => ({ value: r, label: r })),
      },
      {
        key: "status",
        label: t("roles.filterStatus"),
        options: [
          { value: "active", label: t("roles.statusActive") },
          { value: "stub", label: t("roles.statusStub") },
        ],
      },
    ];
  }, [capabilities, t]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return capabilities.filter((cap) => {
      if (needle && !`${cap.name} ${cap.description}`.toLowerCase().includes(needle)) {
        return false;
      }
      for (const [key, values] of Object.entries(filters)) {
        if (!values?.length) continue;
        const actual = key === "resource" ? cap.resource : key === "scope" ? cap.scope : cap.status;
        if (!values.includes(actual)) return false;
      }
      if (view === "byRole" && granted) {
        const isGranted = grantedNames.has(cap.name);
        if (granted === "granted" && !isGranted) return false;
        if (granted === "notGranted" && isGranted) return false;
      }
      return true;
    });
  }, [capabilities, search, filters, view, granted, grantedNames]);

  const filtersActive =
    search.trim().length > 0 ||
    Object.values(filters).some((v) => v?.length) ||
    (view === "byRole" && granted !== null);

  const statusCell = (cap: RbacCapability) =>
    cap.status === "stub" ? (
      <Pill kind="warn">{t("roles.statusStub")}</Pill>
    ) : (
      <span className="text-ap-muted">{t("roles.statusActive")}</span>
    );

  const scopeHeader = (
    <HeaderWithHint label={t("roles.colScope")} hint={t("roles.tipScope")} />
  );
  const statusHeader = (
    <HeaderWithHint label={t("roles.colStatus")} hint={t("roles.tipStatus")} />
  );

  const roleColumns: Column<RbacRole>[] = [
    {
      key: "name",
      header: t("roles.colRole"),
      cell: (role) => {
        const isActive = role.name === activeRole?.name;
        // DataTable wraps this cell in the row's <Link>, which is the focusable
        // element — a second focus target here would be redundant and invalid.
        // `title` carries the description on hover; the sr-only copy puts it in
        // the link's accessible name for screen readers.
        return (
          <span
            title={role.description}
            aria-current={isActive ? "true" : undefined}
            className={isActive ? "font-semibold text-ap-primary" : "text-ap-ink"}
          >
            {isActive ? <span aria-hidden="true">▸ </span> : null}
            {/* Name in its own element so the sr-only description below does
                not fuse with it when queried or read aloud. */}
            <span>{role.name}</span>
            <span className="sr-only"> — {role.description}</span>
          </span>
        );
      },
    },
    {
      key: "tier",
      header: <HeaderWithHint label={t("roles.colTier")} hint={t("roles.tipTier")} />,
      className: "text-xs",
      cell: (role) => t(`roles.tier_${role.tier}`, { defaultValue: role.tier }),
    },
    {
      key: "count",
      header: t("roles.colPermissions"),
      className: "text-end tabular-nums",
      cell: (role) =>
        role.wildcard ? <Pill kind="info">{t("roles.wildcard")}</Pill> : role.capability_count,
    },
    {
      key: "active",
      header: t("roles.statusActive"),
      className: "text-end tabular-nums text-ap-muted",
      cell: (role) => role.active_count,
    },
    {
      key: "stub",
      header: t("roles.statusStub"),
      className: "text-end tabular-nums text-ap-muted",
      cell: (role) => role.stub_count,
    },
    {
      key: "holders",
      header: <HeaderWithHint label={t("roles.colHolders")} hint={t("roles.tipHolders")} />,
      className: "text-end tabular-nums",
      cell: (role) => role.holders.total,
    },
  ];

  const identityCell = (cap: RbacCapability) => (
    <>
      <code className="font-mono text-xs text-ap-ink">{cap.name}</code>
      <div className="text-[11px] text-ap-muted">{cap.description}</div>
    </>
  );

  const byRoleColumns: Column<RbacCapability>[] = [
    { key: "name", header: t("roles.colCapability"), cell: identityCell },
    {
      key: "granted",
      header: <HeaderWithHint label={t("roles.colGranted")} hint={t("roles.tipGranted")} />,
      className: "text-center",
      cell: (cap) =>
        grantedNames.has(cap.name) ? (
          <span className="text-ap-primary" aria-label={t("roles.grantedYes")}>
            ✓
          </span>
        ) : (
          <span className="text-ap-muted" aria-label={t("roles.grantedNo")}>
            —
          </span>
        ),
    },
    {
      key: "scope",
      header: scopeHeader,
      className: "text-xs",
      cell: (cap) => t(`roles.tier_${cap.scope}`, { defaultValue: cap.scope }),
    },
    { key: "status", header: statusHeader, className: "text-xs", cell: statusCell },
  ];

  const byCapabilityColumns: Column<RbacCapability>[] = [
    { key: "name", header: t("roles.colCapability"), cell: identityCell },
    {
      key: "grantedTo",
      header: <HeaderWithHint label={t("roles.colGrantedTo")} hint={t("roles.tipGrantedTo")} />,
      cell: (cap) => {
        const holders = grantedBy.get(cap.name) ?? [];
        if (holders.length === 0) {
          // Defined but unreachable — nobody can ever exercise it.
          return <Pill kind="crit">{t("roles.grantedToNone")}</Pill>;
        }
        return (
          <div className="flex flex-wrap gap-1">
            {holders.map((r) => (
              <Pill key={r.name} kind={r.wildcard ? "info" : "neutral"}>
                {r.name}
              </Pill>
            ))}
          </div>
        );
      },
    },
    {
      key: "scope",
      header: scopeHeader,
      className: "text-xs",
      cell: (cap) => t(`roles.tier_${cap.scope}`, { defaultValue: cap.scope }),
    },
    { key: "status", header: statusHeader, className: "text-xs", cell: statusCell },
  ];

  return (
    <Page>
      <PageHeader
        title={t("roles.title")}
        subtitle={
          data
            ? t("roles.subtitleCounts", {
                roles: roles.length,
                permissions: data.capability_count,
                enforced: data.active_count,
                pending: data.stub_count,
              })
            : t("roles.subtitle")
        }
      />

      <DataTable<RbacRole>
        columns={roleColumns}
        rowKey={(role) => role.name}
        identityKey="name"
        rowHref={(role) => `?role=${encodeURIComponent(role.name)}`}
        state={mapAsyncState(queryState(matrix), (m) => m.roles)}
        caption={t("roles.tableCaptionRoles")}
        errorMessage={t("roles.loadFailed")}
        empty={t("roles.emptyRoles")}
        skeletonRows={5}
      />

      <SegmentedControl<ViewMode>
        items={[
          { value: "byRole", label: t("roles.viewByRole") },
          { value: "byCapability", label: t("roles.viewByCapability") },
        ]}
        value={view}
        onChange={setView}
        ariaLabel={t("roles.viewLabel")}
      />

      <Toolbar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("roles.searchPlaceholder"),
          label: t("roles.searchLabel"),
        }}
        chips={
          view === "byRole" ? (
            <ToolbarChips
              options={[
                { value: "granted", label: t("roles.chipGranted") },
                { value: "notGranted", label: t("roles.chipNotGranted") },
              ]}
              value={granted}
              onChange={setGranted}
              allLabel={t("roles.chipAll")}
            />
          ) : undefined
        }
        axes={axes}
        axisLayout="inline"
        values={filters}
        onValuesChange={setFilters}
        resultCount={{ shown: visible.length, total: capabilities.length }}
      />

      <DataTable<RbacCapability>
        columns={view === "byRole" ? byRoleColumns : byCapabilityColumns}
        rowKey={(cap) => cap.name}
        state={mapAsyncState(queryState(matrix), () => visible)}
        filtered={filtersActive}
        identityKey="name"
        caption={
          view === "byRole" && activeRole
            ? t("roles.tableCaptionRole", {
                role: activeRole.name,
                description: activeRole.description,
              })
            : t("roles.tableCaptionAll")
        }
        errorMessage={t("roles.loadFailed")}
        empty={t("roles.empty")}
        noResults={t("roles.noResults")}
      />
    </Page>
  );
}
