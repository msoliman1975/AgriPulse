import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

import { fetchMe, type Me } from "@/api/me";
import { isApiError } from "@/api/errors";
import { Drawer } from "./Drawer";
import { LanguageToggle } from "./LanguageToggle";
import { UnitToggle } from "./UnitToggle";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsDrawer({ open, onClose }: Props): ReactNode {
  const { t, i18n } = useTranslation("auth");
  const { t: tc } = useTranslation("common");
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !accessToken) return;
    let cancelled = false;
    setError(null);
    fetchMe()
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else if (err instanceof Error) setError(err.message);
        else setError(tc("errors.generic"));
      });
    return () => {
      cancelled = true;
    };
  }, [open, accessToken, tc]);

  return (
    <Drawer open={open} onClose={onClose} title={tc("shell.settingsTitle")}>
      <section className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {tc("shell.preferences")}
        </h3>
        <div className="flex flex-col gap-3">
          <div>
            <span className="mb-1 block text-xs text-slate-500">
              {tc("shell.languageToggle")}
            </span>
            <LanguageToggle />
          </div>
          <div>
            <span className="mb-1 block text-xs text-slate-500">{tc("shell.unitToggle")}</span>
            <UnitToggle />
          </div>
        </div>
      </section>

      <hr className="my-5 border-slate-200" />

      <section className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("me.heading")}
        </h3>
        {error ? (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        ) : !me ? (
          <p role="status" className="text-sm text-slate-600">
            {tc("actions.loading")}
          </p>
        ) : (
          <ProfileBody me={me} lang={i18n.resolvedLanguage} />
        )}
      </section>
    </Drawer>
  );
}

function ProfileBody({ me, lang }: { me: Me; lang: string | undefined }): ReactNode {
  const { t } = useTranslation("auth");
  const lastLoginText = me.last_login_at
    ? new Date(me.last_login_at).toLocaleString(lang)
    : t("me.neverLoggedIn");

  return (
    <div className="space-y-4 text-sm">
      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Row label={t("me.fullName")} value={me.full_name} />
        <Row label={t("me.email")} value={me.email} />
        <Row label={t("me.phone")} value={me.phone ?? "—"} />
        <Row label={t("me.status")} value={me.status} />
        <Row label={t("me.lastLogin")} value={lastLoginText} />
      </dl>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("me.preferences")}
        </h4>
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Row label={t("me.language")} value={me.preferences.language} />
          <Row label={t("me.unitSystem")} value={me.preferences.unit_system} />
          <Row label={t("me.timezone")} value={me.preferences.timezone} />
        </dl>
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("me.platformRoles")}
        </h4>
        {me.platform_roles.length === 0 ? (
          <p className="text-slate-600">—</p>
        ) : (
          <ul className="list-inside list-disc text-slate-700">
            {me.platform_roles.map((r) => (
              <li key={r.role}>{r.role}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("me.tenantMemberships")}
        </h4>
        {me.tenant_memberships.length === 0 ? (
          <p className="text-slate-600">{t("me.noMemberships")}</p>
        ) : (
          <ul className="space-y-2">
            {me.tenant_memberships.map((m) => (
              <li key={m.tenant_id} className="rounded-md border border-slate-200 p-2">
                <p className="font-medium text-slate-800">
                  {m.tenant_name}{" "}
                  <span className="text-xs text-slate-500">({m.tenant_slug})</span>
                </p>
                <p className="text-xs text-slate-500">
                  {t("me.status")}: {m.status}
                </p>
                {m.tenant_roles.length > 0 ? (
                  <p className="text-xs text-slate-700">
                    {t("me.tenantRoleHeader")}: {m.tenant_roles.map((r) => r.role).join(", ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("me.farmScopes")}
        </h4>
        {me.farm_scopes.length === 0 ? (
          <p className="text-slate-600">{t("me.noFarmScopes")}</p>
        ) : (
          <ul className="list-inside list-disc text-slate-700">
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
      <dd className="text-slate-800">{value}</dd>
    </div>
  );
}
