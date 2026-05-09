import type { ReactNode } from "react";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type {
  AdminTenant,
  AdminTenantArchiveEvent,
  AdminTenantSettings,
  AdminTenantSubscription,
} from "@/api/adminTenants";
import { KPICard } from "@/components/KPICard";
import { Skeleton } from "@/components/Skeleton";
import {
  useAdminTenant,
  useAdminTenantMeta,
  useAdminTenantSidecar,
} from "@/queries/admin/tenants";

import { TenantActionPanel } from "../components/TenantActionPanel";
import { TenantAdminsPanel } from "../components/TenantAdminsPanel";
import { TenantStatusBadge } from "../components/TenantStatusBadge";

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
    return <p className="p-6 text-sm text-ap-muted">{t("tenants.detail.loading")}</p>;
  }
  if (tenantQuery.isError || !tenantQuery.data) {
    return (
      <div role="alert" className="mx-auto max-w-lg rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        {t("tenants.detail.errorTitle")}
      </div>
    );
  }

  const tenant = tenantQuery.data;
  const sidecar = sidecarQuery.data;

  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <Link
        to="/platform/tenants"
        className="inline-flex items-center text-sm text-ap-muted hover:text-ap-ink"
      >
        ← {t("tenants.detail.back")}
      </Link>
      <header className="border-b border-ap-line pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-ap-ink">{tenant.name}</h1>
            <p className="mt-1 font-mono text-xs text-ap-muted">{tenant.slug}</p>
          </div>
          <TenantStatusBadge status={tenant.status} />
        </div>
        <p className="mt-2 text-sm text-ap-muted">{t("tenants.detail.subtitle")}</p>
      </header>

      <StatusBanner tenant={tenant} formatter={dateTimeFormatter} />

      <div className="grid gap-4 md:grid-cols-3">
        <KPICard
          title={t("tenants.detail.kpi.members")}
          value={
            sidecar ? (
              sidecar.active_member_count
            ) : (
              <Skeleton className="h-8 w-12" />
            )
          }
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
      </div>

      <ProfileCard tenant={tenant} formatter={dateTimeFormatter} />
      {sidecar?.settings ? (
        <SettingsCard settings={sidecar.settings} />
      ) : null}
      {sidecar?.subscription ? (
        <SubscriptionCard
          subscription={sidecar.subscription}
          formatter={dateTimeFormatter}
        />
      ) : null}
      <AuditCard
        events={sidecar?.recent_events ?? []}
        loading={sidecarQuery.isLoading}
        formatter={dateTimeFormatter}
      />

      <TenantActionPanel
        tenant={tenant}
        purgeGraceDays={metaQuery.data?.purge_grace_days ?? 30}
      />

      <TenantAdminsPanel tenantId={tenant.id} tenantSlug={tenant.slug} />
    </section>
  );
}

interface FormatterProps {
  formatter: Intl.DateTimeFormat;
}

function StatusBanner({
  tenant,
  formatter,
}: { tenant: AdminTenant } & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  if (tenant.status === "active") return null;
  const key = `tenants.detail.banner.${tenant.status}` as const;
  const when = tenant.purge_eligible_at
    ? formatter.format(new Date(tenant.purge_eligible_at))
    : "";
  return (
    <div
      role="status"
      className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
    >
      {t(key, { when })}
      {tenant.last_status_reason ? (
        <p className="mt-1 text-xs text-amber-800/80">{tenant.last_status_reason}</p>
      ) : null}
    </div>
  );
}

function ProfileCard({
  tenant,
  formatter,
}: { tenant: AdminTenant } & FormatterProps): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.profileTitle")}>
      <FieldRow label={t("tenants.detail.fields.id")} value={<code>{tenant.id}</code>} />
      <FieldRow label={t("tenants.detail.fields.schema")} value={<code>{tenant.schema_name}</code>} />
      <FieldRow label={t("tenants.detail.fields.contactEmail")} value={tenant.contact_email} />
      <FieldRow label={t("tenants.detail.fields.contactPhone")} value={tenant.contact_phone ?? "—"} />
      <FieldRow label={t("tenants.detail.fields.locale")} value={tenant.default_locale} />
      <FieldRow label={t("tenants.detail.fields.unitSystem")} value={tenant.default_unit_system} />
      <FieldRow label={t("tenants.detail.fields.timezone")} value={tenant.default_timezone} />
      <FieldRow label={t("tenants.detail.fields.currency")} value={tenant.default_currency} />
      <FieldRow label={t("tenants.detail.fields.country")} value={tenant.country_code} />
      <FieldRow
        label={t("tenants.detail.fields.createdAt")}
        value={formatter.format(new Date(tenant.created_at))}
      />
    </Card>
  );
}

function SettingsCard({ settings }: { settings: AdminTenantSettings }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Card title={t("tenants.detail.settingsTitle")}>
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
          subscription.expires_at
            ? formatter.format(new Date(subscription.expires_at))
            : "—"
        }
      />
      {subscription.trial_start || subscription.trial_end ? (
        <FieldRow
          label={t("tenants.detail.fields.trialWindow")}
          value={`${subscription.trial_start ?? "?"} → ${subscription.trial_end ?? "?"}`}
        />
      ) : null}
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

function Card({ title, children }: { title: string; children: ReactNode }): ReactNode {
  return (
    <section className="rounded-lg border border-ap-line bg-ap-panel p-4 shadow-card">
      <h2 className="border-b border-ap-line pb-2 text-sm font-semibold text-ap-ink">
        {title}
      </h2>
      <dl className="mt-3 space-y-2">{children}</dl>
    </section>
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
