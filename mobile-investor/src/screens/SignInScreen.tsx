import { useState, type ReactNode } from "react";

import { startSignIn } from "@/auth/session";
import { ENDONYM, LANGS, t, type Lang } from "@/i18n";

interface Props {
  lang: Lang;
  onLang: (lang: Lang) => void;
  error: string | null;
}

export function SignInScreen({ lang, onLang, error }: Props): ReactNode {
  const [waiting, setWaiting] = useState(false);
  return (
    <main className="signin">
      <div className="lang-switch" role="group" aria-label={t(lang, "account.language")}>
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
      </div>
      <div className="signin-body">
        <img src="/icon.svg" alt="" className="signin-logo" />
        <h1>{t(lang, "app.name")}</h1>
        <p className="lead">{t(lang, "signIn.title")}</p>
        <p className="muted">{t(lang, "signIn.body")}</p>
        {error ? (
          <p role="alert" className="error">
            {error}
          </p>
        ) : null}
        <button
          type="button"
          className="btn btn-primary btn-block"
          onClick={() => {
            setWaiting(true);
            void startSignIn(lang).finally(() => setWaiting(false));
          }}
        >
          {t(lang, "signIn.button")}
        </button>
        {waiting ? <p className="muted small">{t(lang, "signIn.waiting")}</p> : null}
      </div>
    </main>
  );
}
