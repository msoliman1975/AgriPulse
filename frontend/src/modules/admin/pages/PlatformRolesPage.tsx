import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { RbacCapability, RbacRole } from "@/api/rbacMatrix";
import { Card } from "@/components/Card";
import { DataTable, type Column } from "@/components/DataTable";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Toolbar, ToolbarChips, type FilterAxis, type FilterValues } from "@/components/Toolbar";
import { mapAsyncState, queryState } from "@/components/asyncState";
import { useRbacMatrix } from "@/queries/rbacMatrix";

type ViewMode = "byRole" | "byCapability";

/** Order the tier bands the way authority flows, not alphabetically. */
const TIER_ORDER = ["platform", "tenant", "farm"] as const;

export function PlatformRolesPage(): ReactNode {
  const { t } = useTranslation("admin");
  const matrix = useRbacMatrix();

  const [view, setView] = useState<ViewMode>("byRole");
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<FilterValues>({});
  // Default to "granted only": it turns the first paint into the 20-80 rows
  // that answer "what can this role do?" instead of all 94.
  const [granted, setGranted] = useState<string | null>("granted");

  const data = matrix.data;
  const roles = useMemo(() => data?.roles ?? [], [data]);
  const capabilities = useMemo(() => data?.capabilities ?? [], [data]);

  // Falls back to the first role once loaded, so the detail pane is never
  // an empty frame waiting on a click.
  const activeRole: RbacRole | undefined =
    roles.find((r) => r.name === selectedRole) ?? roles[0];

  const grantedNames = useMemo(
    () => new Set(activeRole?.capabilities ?? []),
    [activeRole],
  );

  /** role name -> the roles granting it, for the by-capability view. */
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
        key: "resource",
        label: t("roles.filterResource"),
        options: resources.map((r) => ({ value: r, label: r })),
      },
      {
        key: "scope",
        label: t("roles.filterScope"),
        options: TIER_ORDER.map((s) => ({ value: s, label: t(`roles.tier_${s}`) })),
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
      header: t("roles.colGranted"),
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
      header: t("roles.colScope"),
      className: "text-xs",
      cell: (cap) => t(`roles.tier_${cap.scope}`, { defaultValue: cap.scope }),
    },
    { key: "status", header: t("roles.colStatus"), className: "text-xs", cell: statusCell },
  ];

  const byCapabilityColumns: Column<RbacCapability>[] = [
    { key: "name", header: t("roles.colCapability"), cell: identityCell },
    {
      key: "grantedTo",
      header: t("roles.colGrantedTo"),
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
      header: t("roles.colScope"),
      className: "text-xs",
      cell: (cap) => t(`roles.tier_${cap.scope}`, { defaultValue: cap.scope }),
    },
    { key: "status", header: t("roles.colStatus"), className: "text-xs", cell: statusCell },
  ];

  return (
    <Page>
      <PageHeader title={t("roles.title")} subtitle={t("roles.subtitle")} />

      <KPIRow columns={3}>
        <KPICard title={t("roles.kpiRoles")} value={roles.length || "—"} />
        <KPICard
          title={t("roles.kpiCapabilities")}
          value={data?.capability_count ?? "—"}
          hint={data ? t("roles.kpiCapabilitiesHint", { n: data.active_count }) : undefined}
        />
        <KPICard
          title={t("roles.kpiPending")}
          value={data?.stub_count ?? "—"}
          hint={t("roles.kpiPendingHint")}
        />
      </KPIRow>

      {TIER_ORDER.map((tier) => {
        const band = roles.filter((r) => r.tier === tier);
        if (band.length === 0) return null;
        return (
          <section key={tier} className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold text-ap-ink">{t(`roles.band_${tier}`)}</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {band.map((role) => {
                const isActive = role.name === activeRole?.name;
                return (
                  <Card
                    key={role.name}
                    title={role.name}
                    actions={
                      role.wildcard ? (
                        <Pill kind="info">{t("roles.wildcard")}</Pill>
                      ) : (
                        <Pill kind="neutral">{role.capability_count}</Pill>
                      )
                    }
                    className={isActive ? "ring-2 ring-ap-primary" : undefined}
                  >
                    <button
                      type="button"
                      className="w-full cursor-pointer text-start hover:opacity-80"
                      onClick={() => {
                        setSelectedRole(role.name);
                        setView("byRole");
                      }}
                      aria-pressed={isActive}
                    >
                      <p className="text-xs text-ap-muted">{role.description}</p>
                      <p className="mt-2 text-xs text-ap-ink">
                        {t("roles.cardCounts", {
                          active: role.active_count,
                          stub: role.stub_count,
                        })}
                      </p>
                      <p className="text-xs text-ap-muted">
                        {t("roles.cardHolders", { n: role.holders.total })}
                      </p>
                    </button>
                  </Card>
                );
              })}
            </div>
          </section>
        );
      })}

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
            ? t("roles.tableCaptionRole", { role: activeRole.name })
            : t("roles.tableCaptionAll")
        }
        errorMessage={t("roles.loadFailed")}
        empty={t("roles.empty")}
        noResults={t("roles.noResults")}
      />
    </Page>
  );
}
