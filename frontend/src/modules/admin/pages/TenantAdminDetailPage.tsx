import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type {
  AdminTenant,
  AdminTenantArchiveEvent,
  AdminTenantSettings,
  AdminTenantSubscription,
} from "@/api/adminTenants";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { StatusBanner } from "@/components/StatusBanner";
import { useAdminTenant, useAdminTenantMeta, useAdminTenantSidecar } from "@/queries/admin/tenants";
import { useCapability } from "@/rbac/useCapability";

import { TenantActionPanel } from "../components/TenantActionPanel";
import { TenantAdminsPanel } from "../components/TenantAdminsPanel";
import { TenantDataPanel } from "../components/TenantDataPanel";
import { TenantIntegrationsPanel } from "../components/TenantIntegrationsPanel";
import { TenantStatusBadge } from "../components/TenantStatusBadge";

type Tab = "profile" | "integrations" | "owner" | "data" | "lifecycle";

export function TenantAdminDetailPage(): ReactNode {
  const { tenantId } = useParams<{ tenantId: string }>();
  const { t, i18n } = useTranslation("admin");

  const tenantQuery = useAdminTenant(tenantId);
  const sidecarQuery = useAdminTenantSidecar(tenantId);
  const metaQuery = useAdminTenantMeta();

  const dateTimeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [i18n.language],
  );

  if (tenantQuery.isLoading) {
    return (
      <Page>
        <Skeleton className="h-64 w-full rounded-xl" />
      </Page>
    );
  }
  if (tenantQuery.isError || !tenantQuery.data) {
    return (
      <Page>
        <ErrorState message={t("tenants.detail.errorTitle")} />
      </Page>
    );
  }

  const tenant = tenantQuery.data;
  const sidecar = sidecarQuery.data;

  return (
    <Page>
      {/* Decision 4C: the same header as every index page — breadcrumb, one
          title scale, status inline with the name. This page used to step
          *down* to text-lg, so opening a tenant read as navigating into
          something lesser than the list it came from. */}
      <PageHeader
        className="border-b border-ap-line pb-4"
        above={
          <Breadcrumb
            items={[
              { label: t("tenants.list.title"), to: "/platform/tenants" },
              { label: tenant.name },
            ]}
          />
        }
        title={tenant.name}
        badge={<TenantStatusBadge status={tenant.status} />}
        subtitle={
          <>
            <span className="font-mono text-xs">{tenant.slug}</span> ·{" "}
            {t("tenants.detail.subtitle")}
          </>
        }
      />

      <TenantStatusNotice tenant={tenant} formatter={dateTimeFormatter} />

      <KPIRow>
        <KPICard
          title={t("tenants.detail.kpi.members")}
          value={sidecar ? sidecar.active_member_count : <Skeleton className="h-8 w-12" />}
        />
        <KPICard
          title={t("tenants.detail.fields.tier")}
          value={sidecar?.subscription?.tier ?? <Skeleton className="h-8 w-20" />}
          hint={sidecar?.subscription?.plan_type ?? undefined}
        />
        {tenant.purge_eligible_at ? (
          <KPICard
            title={t("tenants.detail.kpi.purgeEligible")}
            value={dateTimeFormatter.format(new Date(tenant.purge_eligible_at))}
          />
        ) : null}
      </KPIRow>

      <DetailTabs
        tenant={tenant}
        sidecar={sidecar}
        sidecarLoading={sidecarQuery.isLoading}
        formatter={dateTimeFormatter}
        purgeGraceDays={metaQuery.data?.purge_grace_days ?? 30}
      />
    </Page>
  );
}

interface FormatterProps {
  formatter: Intl.DateTimeFormat;
}

interface DetailTabsProps {
  tenant: AdminTenant;
  sidecar:
    | {
        settings?: AdminTenantSettings | null;
        subscription?: AdminTenantSubscription | null;
        recent_events?: AdminTenantArchiveEvent[] | null;
      }
    | undefined;
  sidecarLoading: boolean;
  formatter: Intl.DateTimeFormat;
  purgeGraceDays: number;
}

function DetailTabs({
  tenant,
  sidecar,
  sidecarLoading,
  formatter,
  purgeGraceDays,
}: DetailTabsProps): ReactNode {
  const { t } = useTranslation("admin");
  const [tab, setTab] = useState<Tab>("profile");
  // The Data tab is purge's only entry point, so it follows the purge
  // capability rather than tenant-page read access — PlatformSupport can read
  // this page but must not be shown a tab whose every action would 403.
  const canPurge = useCapability("platform.purge_data");
  const items: { value: Tab; label: string }[] = [
    { value: "profile", label: t("tenants.detail.tabs.profile") },
    { value: "integrations", label: t("tenants.detail.tabs.integrations") },
    { value: "owner", label: t("tenants.detail.tabs.owner") },
    ...(canPurge ? [{ value: "data" as const, label: t("tenants.detail.tabs.data") }] : []),
    { value: "lifecycle", label: t("tenants.detail.tabs.lifecycle") },
  ];
  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        ariaLabel={t("tenants.detail.tabsLabel")}
        items={items}
        value={tab}
        onChange={(v) => setTab(v)}
      />
      {tab === "profile" ? (
        <>
          <ProfileCard tenant={tenant} formatter={formatter} />
          {sidecar?.settings ? <SettingsCard settings={sidecar.settings} /> : null}
          {sidecar?.subscription ? (
            <SubscriptionCard subscription={sidecar.subscription} formatter={formatter} />
          ) : null}
          <AuditCard
            events={sidecar?.recent_events ?? []}
            loading={sidecarLoading}
            formatter={formatter}
          />
        </>
      ) : tab === "integrations" ? (
        <TenantIntegrationsPanel tenantId={tenant.id} />
      ) : tab === "owner" ? (
        <TenantAdminsPanel tenantId={tenant.id} tenantSlug={tenant.slug} />
      ) : tab === "data" && canPurge ? (
        <TenantDataPanel tenant={tenant} />
      ) : (
        <TenantActionPanel tenant={tenant} purgeGraceDays={purgeGraceDays} />
      )}
    </div>
  );
}

function TenantStatusNotice({
  tenant,
  formatter,
}: { tenant: AdminTenant } & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  if (tenant.status === "active") return null;
  const key = `tenants.detail.banner.${tenant.status}` as const;
  const when = tenant.purge_eligible_at ? formatter.format(new Date(tenant.purge_eligible_at)) : "";
  return (
    <StatusBanner kind="warn" detail={tenant.last_status_reason}>
      {t(key, { when })}
    </StatusBanner>
  );
}

function ProfileCard({ tenant, formatter }: { tenant: AdminTenant } & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.profileTitle")}>
      <dl className="flex flex-col gap-2">
        <FieldRow label={t("tenants.detail.fields.id")} value={<code>{tenant.id}</code>} />
        <FieldRow
          label={t("tenants.detail.fields.schema")}
          value={<code>{tenant.schema_name}</code>}
        />
        <FieldRow label={t("tenants.detail.fields.contactEmail")} value={tenant.contact_email} />
        <FieldRow
          label={t("tenants.detail.fields.contactPhone")}
          value={tenant.contact_phone ?? "—"}
        />
        <FieldRow label={t("tenants.detail.fields.locale")} value={tenant.default_locale} />
        <FieldRow
          label={t("tenants.detail.fields.unitSystem")}
          value={tenant.default_unit_system}
        />
        <FieldRow label={t("tenants.detail.fields.timezone")} value={tenant.default_timezone} />
        <FieldRow label={t("tenants.detail.fields.currency")} value={tenant.default_currency} />
        <FieldRow label={t("tenants.detail.fields.country")} value={tenant.country_code} />
        <FieldRow
          label={t("tenants.detail.fields.createdAt")}
          value={formatter.format(new Date(tenant.created_at))}
        />
      </dl>
    </Card>
  );
}

function SettingsCard({ settings }: { settings: AdminTenantSettings }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.settingsTitle")}>
      <dl className="flex flex-col gap-2">
        <FieldRow
          label={t("tenants.detail.fields.cloudCoverViz")}
          value={`${settings.cloud_cover_threshold_visualization_pct}%`}
        />
        <FieldRow
          label={t("tenants.detail.fields.cloudCoverAnalysis")}
          value={`${settings.cloud_cover_threshold_analysis_pct}%`}
        />
        <FieldRow
          label={t("tenants.detail.fields.imageryCadence")}
          value={settings.imagery_refresh_cadence_hours}
        />
        <FieldRow
          label={t("tenants.detail.fields.alertChannels")}
          value={settings.alert_notification_channels.join(", ") || "—"}
        />
        <FieldRow
          label={t("tenants.detail.fields.webhookUrl")}
          value={settings.webhook_endpoint_url ?? "—"}
        />
        <FieldRow
          label={t("tenants.detail.fields.dashboardIndices")}
          value={settings.dashboard_default_indices.join(", ") || "—"}
        />
      </dl>
    </Card>
  );
}

function SubscriptionCard({
  subscription,
  formatter,
}: {
  subscription: AdminTenantSubscription;
} & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.subscriptionTitle")}>
      <dl className="flex flex-col gap-2">
        <FieldRow label={t("tenants.detail.fields.tier")} value={subscription.tier} />
        <FieldRow
          label={t("tenants.detail.fields.planType")}
          value={subscription.plan_type ?? "—"}
        />
        <FieldRow
          label={t("tenants.detail.fields.startedAt")}
          value={formatter.format(new Date(subscription.started_at))}
        />
        <FieldRow
          label={t("tenants.detail.fields.expiresAt")}
          value={
            subscription.expires_at ? formatter.format(new Date(subscription.expires_at)) : "—"
          }
        />
        {subscription.trial_start || subscription.trial_end ? (
          <FieldRow
            label={t("tenants.detail.fields.trialWindow")}
            value={`${subscription.trial_start ?? "?"} → ${subscription.trial_end ?? "?"}`}
          />
        ) : null}
      </dl>
    </Card>
  );
}

function AuditCard({
  events,
  loading,
  formatter,
}: {
  events: readonly AdminTenantArchiveEvent[];
  loading: boolean;
} & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.auditTitle")}>
      {loading ? (
        <Skeleton className="h-4 w-1/2" />
      ) : events.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("tenants.detail.auditEmpty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line">
          {events.map((event) => (
            <li key={event.id} className="flex justify-between gap-3 py-2 text-sm">
              <span className="font-mono text-xs text-ap-ink">{event.event_type}</span>
              <span className="text-xs text-ap-muted">
                {formatter.format(new Date(event.occurred_at))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function FieldRow({ label, value }: { label: string; value: ReactNode }): ReactNode {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:justify-between">
      <dt className="text-xs uppercase tracking-wide text-ap-muted">{label}</dt>
      <dd className="text-sm text-ap-ink">{value}</dd>
    </div>
  );
}
