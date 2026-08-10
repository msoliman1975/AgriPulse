import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { checkReachability, type Reachability } from "@/api/health";
import { normalisePhone } from "@/auth/phone";
import { SignInError, signIn } from "@/auth/session";
import { LANGS, LOCALES, t, type Lang } from "@/i18n";
import { chooseLang } from "@/i18n/preference";

/**
 * Phone and PIN. No email field anywhere — this persona does not have one, and
 * offering it would be the first thing on screen that does not apply to them.
 *
 * The language picker lives here rather than behind sign-in on purpose: a scout
 * who cannot read the sign-in screen cannot get far enough to change it.
 */
export function SignInScreen({
  lang,
  onLangChange,
  onSignedIn,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  onSignedIn: () => void;
}): ReactNode {
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Reachability | null>(null);
  const [probing, setProbing] = useState(true);

  const probe = useCallback((): void => {
    setProbing(true);
    void checkReachability()
      .then(setHealth)
      .finally(() => setProbing(false));
  }, []);

  useEffect(probe, [probe]);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Normalised here, not in the field: a scout watching their own
      // number get rewritten as they type would reasonably think the app
      // was refusing it. Enrolment stores E.164 as the Keycloak username,
      // so raw input only worked for somebody who typed the + form exactly.
      await signIn(normalisePhone(phone), pin.trim());
      // Device registration is NOT done here: it is farm-gated, and at this
      // instant the farm is still unknown — the token has to be exchanged
      // for /me first. App.tsx registers once the farm resolves.
      onSignedIn();
    } catch (err) {
      setError(err instanceof SignInError ? t(lang, "signIn.invalidCredentials") : String(err));
      // A failure is exactly when "is the server even there?" becomes the
      // question, so re-answer it rather than leaving a stale green dot.
      probe();
    } finally {
      setBusy(false);
    }
  }

  function pickLang(next: Lang): void {
    chooseLang(next);
    onLangChange(next);
  }

  return (
    <form className="screen signin" onSubmit={submit}>
      <div className="logo" />
      <h1>{t(lang, "signIn.title")}</h1>
      <p className="sub">{t(lang, "signIn.subtitle")}</p>

      <HealthPill lang={lang} health={health} probing={probing} onRetry={probe} />

      <label htmlFor="phone">{t(lang, "signIn.phone")}</label>
      <input
        id="phone"
        // A number pad, not a keyboard: the whole credential is digits.
        inputMode="tel"
        autoComplete="username"
        dir="ltr"
        placeholder="+20 100 123 4567"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
      />

      <label htmlFor="pin">{t(lang, "signIn.pin")}</label>
      <input
        id="pin"
        inputMode="numeric"
        type="password"
        autoComplete="current-password"
        dir="ltr"
        maxLength={6}
        value={pin}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
      />

      {error ? <p className="error">{error}</p> : null}

      <button type="submit" disabled={busy || phone.length < 6 || pin.length < 4}>
        {busy ? t(lang, "signIn.working") : t(lang, "signIn.submit")}
      </button>

      <div className="langpick" role="group" aria-label={t(lang, "signIn.language")}>
        {LANGS.map((code) => (
          <button
            key={code}
            type="button"
            className={code === lang ? "lang on" : "lang"}
            aria-pressed={code === lang}
            // Each option is written in its own language — "Arabic" spelled in
            // English helps nobody who needs to switch to Arabic.
            lang={code}
            dir={LOCALES[code].dir}
            onClick={() => pickLang(code)}
          >
            {LOCALES[code].endonym}
          </button>
        ))}
      </div>
    </form>
  );
}

function HealthPill({
  lang,
  health,
  probing,
  onRetry,
}: {
  lang: Lang;
  health: Reachability | null;
  probing: boolean;
  onRetry: () => void;
}): ReactNode {
  if (probing && health === null) {
    return <p className="health checking">{t(lang, "health.checking")}</p>;
  }
  if (health === null) return null;

  const ok = health.api && health.auth;
  const label = ok
    ? "health.ok"
    : !health.api && !health.auth
      ? "health.bothDown"
      : health.api
        ? "health.authDown"
        : "health.apiDown";

  return (
    <p className={ok ? "health ok" : "health bad"}>
      <span aria-hidden="true">{ok ? "●" : "▲"}</span> {t(lang, label)}
      {ok ? null : (
        <>
          {" "}
          <button type="button" className="linkish" onClick={onRetry} disabled={probing}>
            {t(lang, "health.retry")}
          </button>
        </>
      )}
    </p>
  );
}
