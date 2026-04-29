import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchMe, type Me } from "@/api/me";
import { isApiError } from "@/api/errors";

export function MePage(): ReactNode {
  const { t, i18n } = useTranslation("auth");
  const { t: tc } = useTranslation("common");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchMe()
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) {
          setError(err.problem.detail ?? err.problem.title);
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError(tc("errors.generic"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tc]);

  if (error) {
    return (
      <div className="card max-w-3xl" role="alert">
        <p className="text-red-700">{error}</p>
      </div>
    );
  }

  if (!me) {
    return (
      <p role="status" className="p-2 text-slate-600">
        {tc("actions.loading")}
      </p>
    );
  }

  const lastLoginText = me.last_login_at
    ? new Date(me.last_login_at).toLocaleString(i18n.resolvedLanguage)
    : t("me.neverLoggedIn");

  return (
    <div className="space-y-6">
      <div className="card">
        <h1 className="text-2xl font-semibold text-brand-800">{t("me.heading")}</h1>
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Row label={t("me.fullName")} value={me.full_name} />
          <Row label={t("me.email")} value={me.email} />
          <Row label={t("me.phone")} value={me.phone ?? "—"} />
          <Row label={t("me.status")} value={me.status} />
          <Row label={t("me.lastLogin")} value={lastLoginText} />
        </dl>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("me.preferences")}</h2>
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Row label={t("me.language")} value={me.preferences.language} />
          <Row label={t("me.unitSystem")} value={me.preferences.unit_system} />
          <Row label={t("me.timezone")} value={me.preferences.timezone} />
        </dl>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("me.platformRoles")}</h2>
        <ul className="mt-3 list-inside list-disc text-sm text-slate-700">
          {me.platform_roles.length === 0 ? (
            <li>—</li>
          ) : (
            me.platform_roles.map((r) => <li key={r.role}>{r.role}</li>)
          )}
        </ul>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("me.tenantMemberships")}</h2>
        {me.tenant_memberships.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">{t("me.noMemberships")}</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {me.tenant_memberships.map((m) => (
              <li key={m.tenant_id} className="rounded-md border border-slate-200 p-3">
                <p className="font-medium text-slate-800">
                  {m.tenant_name} <span className="text-slate-500">({m.tenant_slug})</span>
                </p>
                <p className="text-xs text-slate-500">
                  {t("me.status")}: {m.status}
                </p>
                {m.tenant_roles.length > 0 ? (
                  <p className="mt-1 text-xs text-slate-700">
                    {t("me.tenantRoleHeader")}: {m.tenant_roles.map((r) => r.role).join(", ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("me.farmScopes")}</h2>
        {me.farm_scopes.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">{t("me.noFarmScopes")}</p>
        ) : (
          <ul className="mt-3 list-inside list-disc text-sm text-slate-700">
            {me.farm_scopes.map((s) => (
              <li key={s.farm_id}>
                {s.farm_id} — {s.role}
              </li>
            ))}
          </ul>
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
