import type { ReactNode } from "react";

import type { Me } from "@/api/client";
import { ENDONYM, LANGS, t, type Lang } from "@/i18n";
import { pick } from "@/screens/HoldingsScreen";
import { APP_VERSION } from "@/version";

export function AccountScreen({
  lang,
  me,
  email,
  onLang,
  onSignOut,
}: {
  lang: Lang;
  me: Me;
  email: string | null;
  onLang: (l: Lang) => void;
  onSignOut: () => void;
}): ReactNode {
  return (
    <section className="screen">
      <dl className="details card">
        <div className="details-row">
          <dt>{t(lang, "account.investor")}</dt>
          <dd>
            {pick(lang, me.full_name, me.full_name_ar)}
            <span className="muted small block">
              {me.code}
              {email ? ` · ${email}` : ""}
            </span>
          </dd>
        </div>
        {me.company_name ? (
          <div className="details-row">
            <dt>{t(lang, "account.company")}</dt>
            <dd>{me.company_name}</dd>
          </div>
        ) : null}
        <div className="details-row">
          <dt>{t(lang, "account.language")}</dt>
          <dd className="lang-switch">
            {LANGS.map((l) => (
              <button
                key={l}
                type="button"
                className={l === lang ? "chip chip-on" : "chip"}
                onClick={() => onLang(l)}
              >
                {ENDONYM[l]}
              </button>
            ))}
          </dd>
        </div>
        <div className="details-row">
          <dt>{t(lang, "account.version")}</dt>
          <dd>{APP_VERSION}</dd>
        </div>
      </dl>
      <button type="button" className="btn btn-danger btn-block" onClick={onSignOut}>
        {t(lang, "account.signOut")}
      </button>
    </section>
  );
}
