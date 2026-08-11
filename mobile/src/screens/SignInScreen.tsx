import { useState, type FormEvent, type ReactNode } from "react";

import { normalisePhone } from "@/auth/phone";
import { SignInError, signIn } from "@/auth/session";
import { t, type Lang } from "@/i18n/strings";

/**
 * Phone and PIN. No email field anywhere — this persona does not have one, and
 * offering it would be the first thing on screen that does not apply to them.
 */
export function SignInScreen({ lang, onSignedIn }: { lang: Lang; onSignedIn: () => void }): ReactNode {
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Normalise here, not in the field: a scout watching their own
      // number get rewritten as they type would reasonably think the app
      // was refusing it.
      await signIn(normalisePhone(phone), pin.trim());
      // Device registration is NOT done here any more: it is farm-gated, and
      // at this instant the farm is still unknown — the token has to be
      // exchanged for /me first. App.tsx registers once the farm resolves.
      onSignedIn();
    } catch (err) {
      setError(err instanceof SignInError ? t(lang, "signIn.invalidCredentials") : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="screen signin" onSubmit={submit}>
      <div className="logo" />
      <h1>{t(lang, "signIn.title")}</h1>
      <p className="sub">{t(lang, "signIn.subtitle")}</p>

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
    </form>
  );
}
