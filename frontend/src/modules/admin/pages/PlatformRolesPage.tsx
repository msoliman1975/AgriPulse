import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import type { RbacCapability, RbacChange, RbacRole } from "@/api/rbacMatrix";
import { DataTable, type Column } from "@/components/DataTable";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { StatusBanner } from "@/components/StatusBanner";
import { Tooltip } from "@/components/Tooltip";
import { Toolbar, ToolbarChips, type FilterAxis, type FilterValues } from "@/components/Toolbar";
import { mapAsyncState, queryState } from "@/components/asyncState";
import { useRbacChanges, useRbacMatrix, useSetRbacOverride } from "@/queries/rbacMatrix";

import { RbacOverrideDialog, type PendingRbacChange } from "../components/RbacOverrideDialog";

type ViewMode = "byRole" | "byCapability" | "changes";

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

/**
 * The granted marker, which becomes a control when the caller may edit.
 *
 * Read-only users keep exactly the Phase 1 glyph. Editors get a real
 * `<button>` — not a checkbox — because activating it opens a confirmation
 * rather than committing, and a checkbox that does not change state on click
 * lies to assistive technology.
 */
function GrantedCell({
  granted,
  overridden,
  editable,
  labels,
  onToggle,
}: {
  granted: boolean;
  overridden: boolean;
  editable: boolean;
  labels: { yes: string; no: string; modified: string; toggle: string };
  onToggle: () => void;
}): ReactNode {
  const glyph = granted ? "✓" : "—";
  const tone = granted ? "text-ap-primary" : "text-ap-muted";

  if (!editable) {
    return (
      <span className={tone} aria-label={granted ? labels.yes : labels.no}>
        {glyph}
        {overridden ? <span className="sr-only"> — {labels.modified}</span> : null}
      </span>
    );
  }

  // A bare glyph in a button was indistinguishable from the read-only glyph —
  // the page looked as though it had no editing at all. The border and hover
  // state are what make it read as a control.
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={granted}
      aria-label={labels.toggle}
      title={labels.toggle}
      className={`min-w-9 rounded border border-ap-line px-2 py-0.5 text-sm hover:border-ap-primary hover:bg-ap-line/40 focus-visible:ring-2 focus-visible:ring-ap-primary ${tone}`}
    >
      {glyph}
      <span className="sr-only"> {granted ? labels.yes : labels.no}</span>
    </button>
  );
}

export function PlatformRolesPage(): ReactNode {
  const { t } = useTranslation("admin");
  const matrix = useRbacMatrix();
  const override = useSetRbacOverride();
  const [pendingChange, setPendingChange] = useState<PendingRbacChange | null>(null);

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

  // Falls back to a role once loaded, so the detail table is never an empty
  // frame waiting on a click — but *not* to `roles[0]`. The list is ordered
  // platform-tier first by permission count, which puts PlatformAdmin on top,
  // and PlatformAdmin is the one role that can never be edited. Landing there
  // hid every toggle and Reset behind a role switch nobody knew to make, so
  // the page read as though runtime editing had not shipped at all.
  //
  // Prefer the first editable role; fall back to the first row only when there
  // is nothing editable (a viewer without `platform.manage_rbac`), where the
  // old behaviour is still the right one.
  const defaultRole = useMemo(
    () => roles.find((r) => !r.immutable && !r.wildcard) ?? roles[0],
    [roles],
  );
  const activeRole: RbacRole | undefined =
    roles.find((r) => r.name === selectedRole) ?? defaultRole;

  const grantedNames = useMemo(() => new Set(activeRole?.capabilities ?? []), [activeRole]);

  /** Capabilities on the active role that differ from the shipped default. */
  const overriddenNames = useMemo(
    () => new Set((activeRole?.overrides ?? []).map((o) => o.capability)),
    [activeRole],
  );

  // The server decides. `can_manage` is computed from the same capability the
  // write endpoint enforces, so the UI cannot offer a control the API refuses.
  // PlatformAdmin is excluded here as well as server-side — its wildcard is
  // immutable, and rendering a dead toggle would just invite the question.
  const canEditActiveRole = Boolean(
    data?.can_manage && activeRole && !activeRole.immutable && !activeRole.wildcard,
  );
  // Captured once so the cell renderers below do not each have to re-assert
  // that `activeRole` is present. Only read when `canEditActiveRole`, which
  // already requires it.
  const activeRoleName = activeRole?.name ?? "";
  const changes = useRbacChanges(view === "changes");

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

  const scopeHeader = <HeaderWithHint label={t("roles.colScope")} hint={t("roles.tipScope")} />;
  const statusHeader = <HeaderWithHint label={t("roles.colStatus")} hint={t("roles.tipStatus")} />;

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
      cell: (cap) => {
        const isGranted = grantedNames.has(cap.name);
        return (
          <GrantedCell
            granted={isGranted}
            overridden={overriddenNames.has(cap.name)}
            editable={canEditActiveRole}
            labels={{
              yes: t("roles.grantedYes"),
              no: t("roles.grantedNo"),
              modified: t("roles.edit.modified"),
              toggle: isGranted
                ? t("roles.edit.toggleRevoke", { capability: cap.name })
                : t("roles.edit.toggleGrant", { capability: cap.name }),
            }}
            onToggle={() =>
              setPendingChange({
                role: activeRoleName,
                capability: cap,
                from: isGranted,
                to: !isGranted,
                granted: !isGranted,
              })
            }
          />
        );
      },
    },
    {
      key: "default",
      header: (
        <HeaderWithHint label={t("roles.edit.colDefault")} hint={t("roles.edit.tipDefault")} />
      ),
      className: "text-center text-xs",
      cell: (cap) => {
        if (!overriddenNames.has(cap.name)) {
          // Unmodified is the overwhelmingly common case; an empty cell keeps
          // the modified ones scannable instead of drowning them in "default".
          return <span className="sr-only">{t("roles.edit.atDefault")}</span>;
        }
        return (
          <div className="flex items-center justify-center gap-1">
            <Pill kind="info">{t("roles.edit.modified")}</Pill>
            {canEditActiveRole ? (
              <button
                type="button"
                onClick={() =>
                  setPendingChange({
                    role: activeRoleName,
                    capability: cap,
                    from: grantedNames.has(cap.name),
                    // Reset restores the shipped default, which — because an
                    // override is only stored when it differs — is always the
                    // opposite of what is in force.
                    to: !grantedNames.has(cap.name),
                    granted: null,
                  })
                }
                className="rounded px-1.5 py-0.5 text-[11px] font-medium text-ap-muted underline underline-offset-2 hover:text-ap-ink"
              >
                {t("roles.edit.reset")}
              </button>
            ) : null}
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

  const changeColumns: Column<RbacChange>[] = [
    {
      key: "changed_at",
      header: t("roles.edit.colWhen"),
      className: "text-xs whitespace-nowrap",
      cell: (row) => new Date(row.changed_at).toLocaleString(),
    },
    {
      key: "what",
      header: t("roles.edit.colWhat"),
      cell: (row) => (
        <>
          <span className="font-semibold text-ap-ink">{row.role}</span>{" "}
          <code className="font-mono text-xs text-ap-ink">{row.capability}</code>
        </>
      ),
    },
    {
      key: "action",
      header: t("roles.edit.colAction"),
      className: "text-xs",
      cell: (row) => (
        <Pill kind={row.action === "revoke" ? "warn" : row.action === "grant" ? "ok" : "neutral"}>
          {t(`roles.edit.action_${row.action}`)}
        </Pill>
      ),
    },
    {
      key: "effect",
      header: t("roles.edit.colEffect"),
      className: "text-xs whitespace-nowrap",
      cell: (row) =>
        `${row.previous_effective ? t("roles.grantedYes") : t("roles.grantedNo")} → ${
          row.new_effective ? t("roles.grantedYes") : t("roles.grantedNo")
        }`,
    },
    {
      key: "who",
      header: t("roles.edit.colWho"),
      className: "text-xs",
      cell: (row) => row.changed_by_email ?? "—",
    },
    {
      key: "note",
      header: t("roles.edit.colNote"),
      className: "text-xs text-ap-muted",
      cell: (row) => row.note ?? "—",
    },
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
          { value: "changes", label: t("roles.edit.viewChanges") },
        ]}
        value={view}
        onChange={setView}
        ariaLabel={t("roles.viewLabel")}
      />

      {view === "changes" ? (
        <DataTable<RbacChange>
          columns={changeColumns}
          rowKey={(row) => String(row.id)}
          state={queryState(changes)}
          caption={t("roles.edit.tableCaptionChanges")}
          errorMessage={t("roles.loadFailed")}
          empty={t("roles.edit.emptyChanges")}
        />
      ) : (
        <>
          {view === "byRole" && activeRole?.wildcard ? (
            <StatusBanner kind="info">{t("roles.edit.wildcardImmutable")}</StatusBanner>
          ) : null}

          {/* Say the feature exists. A toggle that looks like a tick is not a
              discoverable affordance on a page that was read-only until now. */}
          {view === "byRole" && canEditActiveRole ? (
            <StatusBanner kind="info" detail={t("roles.edit.editableDetail")}>
              {t("roles.edit.editableHint", { role: activeRoleName })}
            </StatusBanner>
          ) : null}

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
        </>
      )}

      <RbacOverrideDialog
        change={pendingChange}
        pending={override.isPending}
        propagationSeconds={data?.propagation_seconds ?? 30}
        error={override.error ? t("roles.edit.saveFailed") : null}
        onClose={() => {
          setPendingChange(null);
          override.reset();
        }}
        onConfirm={(note) => {
          if (!pendingChange) return;
          override.mutate(
            {
              role: pendingChange.role,
              capability: pendingChange.capability.name,
              granted: pendingChange.granted,
              note: note || undefined,
            },
            { onSuccess: () => setPendingChange(null) },
          );
        }}
      />
    </Page>
  );
}
