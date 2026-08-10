import { useState, type FormEvent, type ReactNode } from "react";

import { SignInError, signIn } from "@/auth/session";
import { t, type Lang } from "@/i18n/strings";
import { ensureDeviceRegistered } from "@/push/register";

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
      await signIn(phone.trim(), pin.trim());
      // Deliberately not awaited: a slow or refused permission prompt must
      // not hold a scout on the sign-in screen. Push is a convenience; the
      // visit list is the source of truth.
      void ensureDeviceRegistered();
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
