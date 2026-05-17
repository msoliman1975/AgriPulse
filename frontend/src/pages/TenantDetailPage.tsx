import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

import { fetchMe, type Me, type TenantMembership } from "@/api/me";
import { listFarms, type Farm } from "@/api/farms";
import { isApiError } from "@/api/errors";
import { decodeJwt } from "@/rbac/jwt";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

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
      <p role="alert" className="text-sm text-red-700">
        {error}
      </p>
    );
  }
  if (!me) {
    return (
      <p role="status" className="text-sm text-slate-600">
        {t("actions.loading")}
      </p>
    );
  }

  const membership: TenantMembership | undefined = me.tenant_memberships.find(
    (m) => m.tenant_id === tenantId,
  );

  if (!membership) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {t("errors.notFound")}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-brand-800">{membership.tenant_name}</h1>
        <p className="text-sm text-slate-600">
          {membership.tenant_slug} ·{" "}
          {t(`shell.tenantStatus.${membership.status}`, membership.status)}
        </p>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("tenant.metadata")}</h2>
        <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
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
        </dl>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{tFarms("nav.farms")}</h2>
        {!isActiveTenant ? (
          <p className="mt-2 text-sm text-slate-600">{t("tenant.switchToView")}</p>
        ) : farms === null ? (
          <p role="status" className="mt-2 text-sm text-slate-600">
            {t("actions.loading")}
          </p>
        ) : farms.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">{tFarms("list.empty")}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-start text-xs uppercase text-slate-500">
                  <th className="py-2 text-start">{tFarms("list.columns.code")}</th>
                  <th className="py-2 text-start">{tFarms("list.columns.name")}</th>
                  <th className="py-2 text-start">{tFarms("list.columns.governorate")}</th>
                  <th className="py-2 text-start">{tFarms("list.columns.area")}</th>
                  <th className="py-2 text-start">{tFarms("list.columns.status")}</th>
                </tr>
              </thead>
              <tbody>
                {farms.map((f) => (
                  <tr key={f.id} className="border-t border-slate-100">
                    <td className="py-2">
                      <Link to={`/farms/${f.id}`} className="text-brand-700 underline">
                        {f.code}
                      </Link>
                    </td>
                    <td className="py-2">{f.name}</td>
                    <td className="py-2">{f.governorate ?? "—"}</td>
                    <td className="py-2">
                      <AreaDisplay areaM2={Number(f.area_m2)} />
                    </td>
                    <td className="py-2">
                      {tFarms(f.is_active ? "status.active" : "status.archived")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-800">{value}</dd>
    </div>
  );
}
