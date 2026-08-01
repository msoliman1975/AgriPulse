import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

import { fetchMe, type Me, type TenantMembership } from "@/api/me";
import { listFarms, type Farm } from "@/api/farms";
import { isApiError } from "@/api/errors";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { decodeJwt } from "@/rbac/jwt";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { Page } from "@/components/Page";

export function TenantDetailPage(): ReactNode {
  const { tenantId = "" } = useParams<{ tenantId: string }>();
  const { t } = useTranslation("common");
  const { t: tFarms } = useTranslation("farms");
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const activeTenantId = decodeJwt(accessToken)?.tenant_id ?? null;
  const isActiveTenant = activeTenantId === tenantId;

  const [me, setMe] = useState<Me | null>(null);
  const [farms, setFarms] = useState<Farm[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    setError(null);
    const promises: [Promise<Me>, Promise<Farm[] | null>] = [
      fetchMe(),
      isActiveTenant ? listFarms().then((p) => p.items) : Promise.resolve(null),
    ];
    Promise.all(promises)
      .then(([m, fs]) => {
        if (cancelled) return;
        setMe(m);
        setFarms(fs);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, isActiveTenant, tenantId]);

  if (error) {
    return (
      <Page>
        <ErrorState message={error} />
      </Page>
    );
  }
  if (!me) {
    return (
      <p role="status" className="text-sm text-ap-muted">
        {t("actions.loading")}
      </p>
    );
  }

  const membership: TenantMembership | undefined = me.tenant_memberships.find(
    (m) => m.tenant_id === tenantId,
  );

  if (!membership) {
    return (
      <Page>
        <ErrorState message={t("errors.notFound")} />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        title={membership.tenant_name}
        subtitle={`${membership.tenant_slug} · ${t(`shell.tenantStatus.${membership.status}`, membership.status)}`}
      />

      <Card title={t("tenant.metadata")} bodyClassName="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Row label={t("tenant.id")} value={membership.tenant_id} />
        <Row label={t("tenant.slug")} value={membership.tenant_slug} />
        <Row label={t("tenant.status")} value={membership.status} />
        <Row
          label={t("tenant.joinedAt")}
          value={membership.joined_at ? new Date(membership.joined_at).toLocaleDateString() : "—"}
        />
        <Row
          label={t("tenant.roles")}
          value={
            membership.tenant_roles.length === 0
              ? "—"
              : membership.tenant_roles.map((r) => r.role).join(", ")
          }
        />
      </Card>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-ap-ink">{tFarms("nav.farms")}</h2>
        {!isActiveTenant ? (
          <Card>
            <p className="text-sm text-ap-muted">{t("tenant.switchToView")}</p>
          </Card>
        ) : (
          <DataTable<Farm>
            columns={[
              { key: "code", header: tFarms("list.columns.code"), cell: (f) => f.code },
              { key: "name", header: tFarms("list.columns.name"), cell: (f) => f.name },
              {
                key: "governorate",
                header: tFarms("list.columns.governorate"),
                className: "text-ap-muted",
                cell: (f) => f.governorate ?? "—",
              },
              {
                key: "area",
                header: tFarms("list.columns.area"),
                align: "end",
                cell: (f) => <AreaDisplay areaM2={Number(f.area_m2)} />,
              },
              {
                key: "status",
                header: tFarms("list.columns.status"),
                cell: (f) => (
                  <Pill kind={f.is_active ? "ok" : "neutral"}>
                    {tFarms(f.is_active ? "status.active" : "status.archived")}
                  </Pill>
                ),
              },
            ]}
            rowKey={(f) => f.id}
            state={farms === null ? { status: "loading" } : { status: "success", data: farms }}
            rowHref={(f) => `/farms/${f.id}`}
            caption={tFarms("nav.farms")}
            empty={<EmptyState message={tFarms("list.empty")} />}
          />
        )}
      </div>
    </Page>
  );
}

function Row({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-ap-muted">{label}</div>
      <div className="text-sm text-ap-ink">{value}</div>
    </div>
  );
}
