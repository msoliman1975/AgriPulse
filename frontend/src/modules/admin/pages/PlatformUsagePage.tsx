import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ErrorDenseRoute,
  FeatureAdoption,
  FlowFunnel,
  RecentError,
  RetryStorm,
  RouteDwell,
  SlowAction,
  TenantHealth,
  UsageOverview,
} from "@/api/usage";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Sparkline } from "@/components/Sparkline";
import { queryState } from "@/components/asyncState";
import { useUsageFilterOptions, useUsageOverview } from "@/queries/usage";

/**
 * `/platform/usage` — how the product is actually used (TEL-7).
 *
 * Answers the four questions the telemetry plan exists for: how is it used,
 * where does time go, which capabilities matter, and where do people struggle.
 *
 * Two things about this page are decisions, not defaults:
 *
 *  - **Platform staff are excluded unless you ask for them.** On a pilot-scale
 *    product our own clicking outweighs the customers', so the honest default
 *    is off. The toggle is visible rather than hidden so nobody reads a number
 *    without knowing which population it describes.
 *  - **Every table says what it means, not just what it counts.** "Cold
 *    capabilities" is the delete list; "error-dense" is the fix list. A table
 *    of numbers with no stated purpose gets read once and never again.
 */

const SPANS = [7, 30, 90] as const;
type Span = (typeof SPANS)[number];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Durations are read, not calculated with — minutes and seconds beat 4200 ms. */
function humanMs(ms: number, unit: { s: string; m: string; h: string }): string {
  if (ms < 1000) return `0${unit.s}`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 90) return `${String(seconds)}${unit.s}`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${String(minutes)}${unit.m}`;
  return `${String(Math.round(minutes / 60))}${unit.h}`;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function PlatformUsagePage(): ReactNode {
  const { t } = useTranslation("admin");
  const [span, setSpan] = useState<Span>(30);
  const [includeStaff, setIncludeStaff] = useState(false);
  const [tenantId, setTenantId] = useState<string>("");
  const [userId, setUserId] = useState<string>("");

  const range = useMemo(() => ({ start: isoDaysAgo(span - 1), end: today() }), [span]);
  // The option lists are fetched for the same window and narrowed by the tenant
  // choice, so picking a tenant also shortens the people list to that tenant's
  // users instead of offering everyone.
  const options = useUsageFilterOptions({ ...range, tenantId, includeStaff });
  const query = useMemo(
    () => ({ ...range, tenantId, userId, includeStaff }),
    [range, tenantId, userId, includeStaff],
  );
  const overview = useUsageOverview(query);
  const state = queryState(overview);

  // A person belongs to one tenant, so a selection from a wider list can stop
  // being valid the moment a tenant is chosen. Clearing it is better than
  // silently querying a combination that returns nothing.
  const userOptions = options.data?.users ?? [];
  const selectedUserStillValid = userId === "" || userOptions.some((u) => u.user_id === userId);
  if (!selectedUserStillValid && options.data) setUserId("");

  const unit = {
    s: t("usage.unit.seconds"),
    m: t("usage.unit.minutes"),
    h: t("usage.unit.hours"),
  };

  return (
    <Page>
      <PageHeader
        title={t("usage.title")}
        subtitle={t("usage.subtitle")}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <SegmentedControl
              value={String(span)}
              onChange={(v) => setSpan(Number(v) as Span)}
              ariaLabel={t("usage.spanLabel")}
              items={SPANS.map((d) => ({
                value: String(d),
                label: t("usage.span", { count: d }),
              }))}
            />
            <FilterSelect
              label={t("usage.filter.tenant")}
              value={tenantId}
              allLabel={t("usage.filter.allTenants")}
              onChange={(v) => {
                setTenantId(v);
                // A person belongs to one tenant; keeping a stale pick would
                // query a pair that cannot match.
                setUserId("");
              }}
              options={(options.data?.tenants ?? []).map((o) => ({
                value: o.tenant_id,
                label: `${o.label} (${String(o.events)})`,
              }))}
            />
            <FilterSelect
              label={t("usage.filter.user")}
              value={userId}
              allLabel={t("usage.filter.allUsers")}
              onChange={setUserId}
              options={userOptions.map((o) => ({
                value: o.user_id,
                label: o.actor_role
                  ? `${o.label} · ${o.actor_role} (${String(o.events)})`
                  : `${o.label} (${String(o.events)})`,
              }))}
            />
            <label className="flex items-center gap-2 text-xs text-ap-muted">
              <input
                type="checkbox"
                checked={includeStaff}
                onChange={(e) => setIncludeStaff(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-ap-line"
              />
              {t("usage.includeStaff")}
            </label>
          </div>
        }
      />

      <AsyncBoundary
        state={state}
        skeleton="lines"
        skeletonLines={6}
        empty={<EmptyState message={t("usage.empty.body")} />}
        isEmpty={(d: UsageOverview) => d.daily.length === 0 && d.kpis.mau === 0}
      >
        {(data) => (
          <div className="flex flex-col gap-6">
            <Kpis data={data} unit={unit} />
            <TimeSection rows={data.routes} unit={unit} />
            <AdoptionSection
              features={data.features}
              cold={data.cold_features}
              scoped={userId !== "" || tenantId !== ""}
            />
            <FunnelSection funnels={data.funnels} />
            <StruggleSection
              routes={data.error_routes}
              errors={data.recent_errors}
              storms={data.retry_storms}
              slow={data.slow_actions}
              unit={unit}
            />
            {/* Hidden under a person filter: it would always be exactly one
                row, which says nothing the picker did not already say. */}
            {userId === "" ? <TenantSection rows={data.tenants} /> : null}
          </div>
        )}
      </AsyncBoundary>
    </Page>
  );
}

type Unit = { s: string; m: string; h: string };

/**
 * A labelled dropdown with an explicit "all" choice.
 *
 * A native `<select>` rather than a combobox: the lists are capped server-side
 * at 200 tenants and 500 people, ordered by event count, and a native control
 * gets keyboard access and type-ahead for free.
 */
function FilterSelect({
  label,
  value,
  allLabel,
  onChange,
  options,
}: {
  label: string;
  value: string;
  allLabel: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}): ReactNode {
  return (
    <label className="flex items-center gap-1.5 text-xs text-ap-muted">
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[14rem] rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs text-ap-ink"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}): ReactNode {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold text-ap-ink">{title}</h2>
        {/* The hint is the point of the section. Without it a reader has to
            infer what the numbers are for, and mostly does not bother. */}
        <p className="text-xs text-ap-muted">{hint}</p>
      </div>
      {children}
    </section>
  );
}

function Kpis({ data, unit }: { data: UsageOverview; unit: Unit }): ReactNode {
  const { t } = useTranslation("admin");
  const series = data.daily.map((d) => d.users);
  return (
    <KPIRow columns={4}>
      <KPICard
        title={t("usage.kpi.dau")}
        value={data.kpis.dau}
        hint={t("usage.kpi.dauHint")}
        sparkline={<Sparkline points={series} ariaLabel={t("usage.kpi.dauHint")} />}
      />
      <KPICard title={t("usage.kpi.wau")} value={data.kpis.wau} hint={t("usage.kpi.wauHint")} />
      <KPICard
        title={t("usage.kpi.stickiness")}
        value={percent(data.kpis.stickiness)}
        hint={t("usage.kpi.stickinessHint")}
      />
      <KPICard
        title={t("usage.kpi.session")}
        value={humanMs(data.kpis.median_session_seconds * 1000, unit)}
        hint={t("usage.kpi.sessionHint", {
          count: Math.round(data.kpis.sessions_per_user * 10) / 10,
        })}
      />
    </KPIRow>
  );
}

function TimeSection({ rows, unit }: { rows: RouteDwell[]; unit: Unit }): ReactNode {
  const { t } = useTranslation("admin");
  const max = Math.max(1, ...rows.map((r) => r.total_ms));
  const columns: ReadonlyArray<Column<RouteDwell>> = [
    { key: "route", header: t("usage.time.route"), cell: (r) => <code>{r.route}</code> },
    {
      key: "bar",
      header: t("usage.time.total"),
      cell: (r) => (
        <div className="flex items-center gap-2">
          {/* A bar, not just a number: rank is the question here, and eyes
              compare lengths faster than they compare six-digit integers. */}
          <div
            className="h-2 rounded-full bg-ap-primary"
            style={{ width: `${String(Math.max(2, (r.total_ms / max) * 100))}%` }}
          />
          <span className="whitespace-nowrap text-xs text-ap-muted">
            {humanMs(r.total_ms, unit)}
          </span>
        </div>
      ),
    },
    { key: "visits", header: t("usage.time.visits"), align: "end", cell: (r) => r.visits },
    {
      key: "median",
      header: t("usage.time.median"),
      align: "end",
      cell: (r) => humanMs(r.median_ms, unit),
    },
  ];
  return (
    <Section title={t("usage.time.title")} hint={t("usage.time.hint")}>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.route}
        empty={<EmptyState message={t("usage.time.empty")} />}
      />
    </Section>
  );
}

function AdoptionSection({
  features,
  cold,
  scoped,
}: {
  features: FeatureAdoption[];
  cold: string[];
  /** True when a tenant or person filter is active. "Cold" then means "unused
   *  by them", not "unused by anyone" — a very different conclusion, and one
   *  nobody should have to infer from the filter bar. */
  scoped: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const columns: ReadonlyArray<Column<FeatureAdoption>> = [
    { key: "feature", header: t("usage.adoption.feature"), cell: (r) => r.feature },
    { key: "users", header: t("usage.adoption.users"), align: "end", cell: (r) => r.users },
    { key: "tenants", header: t("usage.adoption.tenants"), align: "end", cell: (r) => r.tenants },
    { key: "events", header: t("usage.adoption.events"), align: "end", cell: (r) => r.events },
    {
      key: "last",
      header: t("usage.adoption.lastUsed"),
      align: "end",
      cell: (r) => r.last_used ?? "—",
    },
  ];
  return (
    <Section title={t("usage.adoption.title")} hint={t("usage.adoption.hint")}>
      <DataTable
        columns={columns}
        rows={features}
        rowKey={(r) => r.feature}
        empty={<EmptyState message={t("usage.adoption.empty")} />}
      />
      <Card className="mt-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
          {t("usage.cold.title")}
        </h3>
        <p className="mt-1 text-xs text-ap-muted">
          {scoped ? t("usage.cold.hintScoped") : t("usage.cold.hint")}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {cold.length === 0 ? (
            <span className="text-xs text-ap-muted">{t("usage.cold.none")}</span>
          ) : (
            cold.map((f) => (
              <Pill key={f} kind="warn">
                {f}
              </Pill>
            ))
          )}
        </div>
      </Card>
    </Section>
  );
}

function FunnelSection({ funnels }: { funnels: FlowFunnel[] }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Section title={t("usage.funnel.title")} hint={t("usage.funnel.hint")}>
      {funnels.length === 0 ? (
        <EmptyState message={t("usage.funnel.empty")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {funnels.map((f) => {
            const rate = f.entries === 0 ? 0 : f.completions / f.entries;
            return (
              <Card key={f.flow}>
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="text-sm font-medium text-ap-ink">{f.flow}</h3>
                  <span className="text-sm font-semibold text-ap-ink">{percent(rate)}</span>
                </div>
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-ap-line">
                  <div
                    className="h-full bg-ap-primary"
                    style={{ width: `${String(rate * 100)}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-ap-muted">
                  {t("usage.funnel.counts", {
                    entries: f.entries,
                    completions: f.completions,
                    abandoned: f.abandoned,
                  })}
                </p>
                {f.abandoned > 0 ? (
                  <p className="mt-1 text-xs text-ap-warn">
                    {/* died_at is null when they left before any step — that is
                        not "unknown", it is "bounced at entry", and saying so
                        points at a different fix. */}
                    {f.died_at
                      ? t("usage.funnel.diedAt", { step: f.died_at })
                      : t("usage.funnel.diedAtEntry")}
                  </p>
                ) : null}
              </Card>
            );
          })}
        </div>
      )}
    </Section>
  );
}

function StruggleSection({
  routes,
  errors,
  storms,
  slow,
  unit,
}: {
  routes: ErrorDenseRoute[];
  errors: RecentError[];
  storms: RetryStorm[];
  slow: SlowAction[];
  unit: Unit;
}): ReactNode {
  const { t } = useTranslation("admin");

  const routeCols: ReadonlyArray<Column<ErrorDenseRoute>> = [
    { key: "route", header: t("usage.time.route"), cell: (r) => <code>{r.route}</code> },
    { key: "views", header: t("usage.struggle.views"), align: "end", cell: (r) => r.views },
    { key: "errors", header: t("usage.struggle.errors"), align: "end", cell: (r) => r.errors },
    {
      key: "rate",
      header: t("usage.struggle.rate"),
      align: "end",
      cell: (r) => <span className="font-medium text-ap-crit">{percent(r.error_rate)}</span>,
    },
  ];

  const errorCols: ReadonlyArray<Column<RecentError>> = [
    { key: "time", header: t("usage.struggle.when"), cell: (r) => r.time.slice(0, 19) },
    { key: "route", header: t("usage.time.route"), cell: (r) => <code>{r.route ?? "—"}</code> },
    {
      key: "code",
      header: t("usage.struggle.code"),
      cell: (r) => `${r.method ?? ""} ${r.error_code ?? ""}`.trim() || "—",
    },
    {
      key: "correlation",
      header: t("usage.struggle.correlation"),
      // The whole reason this table exists: paste this into the log query and
      // you have the server side of a failure a real person saw.
      cell: (r) => <code className="text-[11px]">{r.correlation_id ?? "—"}</code>,
    },
  ];

  const stormCols: ReadonlyArray<Column<RetryStorm>> = [
    { key: "feature", header: t("usage.adoption.feature"), cell: (r) => r.feature ?? "—" },
    { key: "action", header: t("usage.struggle.action"), cell: (r) => r.action ?? "—" },
    { key: "storms", header: t("usage.struggle.storms"), align: "end", cell: (r) => r.storms },
    { key: "users", header: t("usage.adoption.users"), align: "end", cell: (r) => r.users },
  ];

  const slowCols: ReadonlyArray<Column<SlowAction>> = [
    { key: "feature", header: t("usage.adoption.feature"), cell: (r) => r.feature },
    {
      key: "p95",
      header: t("usage.struggle.p95"),
      align: "end",
      cell: (r) => humanMs(r.p95_ms, unit),
    },
    { key: "samples", header: t("usage.struggle.samples"), align: "end", cell: (r) => r.samples },
  ];

  return (
    <Section title={t("usage.struggle.title")} hint={t("usage.struggle.hint")}>
      <div className="flex flex-col gap-4">
        <SubTable label={t("usage.struggle.dense")}>
          <DataTable
            columns={routeCols}
            rows={routes}
            rowKey={(r) => r.route}
            empty={<EmptyState message={t("usage.struggle.noneDense")} />}
          />
        </SubTable>
        <SubTable label={t("usage.struggle.recent")}>
          <DataTable
            columns={errorCols}
            rows={errors}
            rowKey={(r) => `${r.time}-${r.correlation_id ?? r.route ?? ""}`}
            empty={<EmptyState message={t("usage.struggle.noneRecent")} />}
          />
        </SubTable>
        <SubTable label={t("usage.struggle.stormsTitle")}>
          <DataTable
            columns={stormCols}
            rows={storms}
            rowKey={(r) => `${r.feature ?? ""}-${r.action ?? ""}`}
            empty={<EmptyState message={t("usage.struggle.noneStorms")} />}
          />
        </SubTable>
        <SubTable label={t("usage.struggle.slowTitle")}>
          <DataTable
            columns={slowCols}
            rows={slow}
            rowKey={(r) => r.feature}
            empty={<EmptyState message={t("usage.struggle.noneSlow")} />}
          />
        </SubTable>
      </div>
    </Section>
  );
}

function SubTable({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ap-muted">{label}</h3>
      {children}
    </div>
  );
}

function TenantSection({ rows }: { rows: TenantHealth[] }): ReactNode {
  const { t } = useTranslation("admin");
  const columns: ReadonlyArray<Column<TenantHealth>> = [
    {
      key: "tenant",
      header: t("usage.tenant.tenant"),
      cell: (r) => <span className="font-medium">{r.label}</span>,
    },
    {
      key: "last",
      header: t("usage.tenant.lastSeen"),
      align: "end",
      cell: (r) => r.last_seen ?? "—",
    },
    { key: "wau", header: t("usage.kpi.wau"), align: "end", cell: (r) => r.wau },
    {
      key: "breadth",
      header: t("usage.tenant.breadth"),
      align: "end",
      cell: (r) => r.features_used,
    },
    { key: "events", header: t("usage.adoption.events"), align: "end", cell: (r) => r.events },
  ];
  return (
    <Section title={t("usage.tenant.title")} hint={t("usage.tenant.hint")}>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.tenant_id}
        rowHref={(r) => `/platform/tenants/${r.tenant_id}`}
        identityKey="tenant"
        empty={<EmptyState message={t("usage.tenant.empty")} />}
      />
    </Section>
  );
}
