import { useState, type FormEvent, type ReactNode } from "react";

import { ApiError, changeOwnPin } from "@/api/client";
import type { FarmScope } from "@/api/me";
import { sessionPhone, signIn, signOut } from "@/auth/session";
import { t, type Lang } from "@/i18n";
import { resetLangOnSignOut } from "@/i18n/preference";
import { releaseDevice } from "@/push/register";

/**
 * What is left of the Me tab.
 *
 * That tab held three things and had exclusive claim to none of them. The farm
 * rail states the farms and counts them, which the tab's read-only list never
 * did. The header states the language, and has to, because a handset changes
 * hands and somebody who cannot read the current language cannot navigate to a
 * screen named in it. That left signing out — a third of the tab bar for one
 * button nobody presses on purpose more than once a day.
 *
 * So it became a sheet behind the name. **Not a button in the header**: sign
 * out sitting loose beside the rows a scout taps all day is the exact problem
 * the Me tab was built to solve, and undoing that to save a tab would trade a
 * navigation nicety for a scout locked out of the app standing in a block.
 *
 * The farm list stays, and stays read-only, for the one fact nothing else on
 * screen carries: the role held on each farm. It must not carry a single
 * affordance suggesting otherwise — this list used to change what the whole app
 * showed, and nothing on the Tasks tab said so.
 */
export function AccountSheet({
  lang,
  name,
  farms,
  farmName,
  onClose,
}: {
  lang: Lang;
  name: string | null;
  farms: FarmScope[];
  /** Id -> the name people call it, falling back to the id when unknown. */
  farmName: (farmId: string) => string;
  onClose: () => void;
}): ReactNode {
  const [signingOut, setSigningOut] = useState(false);
  const [changingPin, setChangingPin] = useState(false);
  const [pinChanged, setPinChanged] = useState(false);

  return (
    <div className="sheet-wrap" onClick={onClose}>
      <div className="sheet acct" onClick={(e) => e.stopPropagation()}>
        <span className="grab" />

        <h2 dir="auto">{name || t(lang, "me.title")}</h2>

        <h3 className="section">{farms.length === 1 ? t(lang, "me.farm") : t(lang, "me.farms")}</h3>
        <ul className="farms">
          {farms.map((f) => (
            <li key={f.farm_id} className="static">
              <span className="fname" dir="auto">
                {farmName(f.farm_id)}
              </span>
              <span className="role">{f.role}</span>
            </li>
          ))}
        </ul>
        {/* Says what this list is *not*, which is the thing a scout who
            remembers the old settings screen will assume it still is. */}
        <p className="hint">{t(lang, farms.length === 1 ? "me.roleHint" : "me.farmsHint")}</p>

        {changingPin ? (
          <ChangePinForm
            lang={lang}
            onCancel={() => setChangingPin(false)}
            onDone={() => {
              setChangingPin(false);
              setPinChanged(true);
            }}
          />
        ) : (
          <button
            type="button"
            className="link"
            onClick={() => {
              setPinChanged(false);
              setChangingPin(true);
            }}
          >
            {t(lang, "pin.change")}
          </button>
        )}
        {pinChanged ? (
          <p className="hint" role="status">
            {t(lang, "pin.done")}
          </p>
        ) : null}

        <button
          type="button"
          className="signout"
          disabled={signingOut}
          onClick={() => {
            setSigningOut(true);
            // A handset passed to the next scout should open in *their*
            // language, unless somebody deliberately set this device's.
            resetLangOnSignOut();
            // Revoke first and await it: the request authenticates with the
            // access token, so clearing the session or reloading before it
            // lands would cancel it and leave this handset receiving a
            // departed scout's visits.
            void releaseDevice()
              .finally(signOut)
              .finally(() => location.reload());
          }}
        >
          {t(lang, signingOut ? "visits.signingOut" : "visits.signOut")}
        </button>

        <button type="button" className="link" onClick={onClose}>
          {t(lang, "me.close")}
        </button>
      </div>
    </div>
  );
}

/**
 * Replace the PIN a supervisor read out. Until this is done they know it too.
 *
 * Changing it ends every session, this phone's included, so it signs straight
 * back in. If that fails the old session is already dead, so the honest next
 * step is the sign-in screen, where the new PIN works.
 */
function ChangePinForm({
  lang,
  onCancel,
  onDone,
}: {
  lang: Lang;
  onCancel: () => void;
  onDone: () => void;
}): ReactNode {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const digits = (value: string): string => value.replace(/\D/g, "");

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (next !== repeat) {
      setError(t(lang, "pin.errMatch"));
      return;
    }
    // Read before the change: ending the session is part of it.
    const phone = sessionPhone();
    setBusy(true);
    setError(null);
    try {
      await changeOwnPin(current, next);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        t(
          lang,
          status === 403 ? "pin.errWrong" : status === 422 ? "pin.errWeak" : "pin.errFailed",
        ),
      );
      setBusy(false);
      return;
    }
    try {
      if (!phone) throw new Error("no phone on the session");
      await signIn(phone, next);
      onDone();
    } catch {
      await signOut();
      location.reload();
    }
  }

  return (
    <form className="pinform" onSubmit={submit}>
      <label htmlFor="pin-current">{t(lang, "pin.current")}</label>
      <input
        id="pin-current"
        inputMode="numeric"
        type="password"
        autoComplete="current-password"
        dir="ltr"
        maxLength={6}
        value={current}
        onChange={(e) => setCurrent(digits(e.target.value))}
      />
      <label htmlFor="pin-new">{t(lang, "pin.new")}</label>
      <input
        id="pin-new"
        inputMode="numeric"
        type="password"
        autoComplete="new-password"
        dir="ltr"
        maxLength={6}
        value={next}
        onChange={(e) => setNext(digits(e.target.value))}
      />
      <label htmlFor="pin-repeat">{t(lang, "pin.repeat")}</label>
      <input
        id="pin-repeat"
        inputMode="numeric"
        type="password"
        autoComplete="new-password"
        dir="ltr"
        maxLength={6}
        value={repeat}
        onChange={(e) => setRepeat(digits(e.target.value))}
      />
      {error ? <p className="error">{error}</p> : null}
      <button type="submit" disabled={busy || current.length < 4 || next.length !== 6}>
        {busy ? t(lang, "pin.saving") : t(lang, "pin.save")}
      </button>
      <button type="button" className="link" disabled={busy} onClick={onCancel}>
        {t(lang, "pin.cancel")}
      </button>
    </form>
  );
}
