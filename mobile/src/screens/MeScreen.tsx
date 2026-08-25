import { useState, type ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { signOut } from "@/auth/session";
import { LANGS, LOCALES, t, type Lang } from "@/i18n";
import { chooseLang, resetLangOnSignOut } from "@/i18n/preference";
import { releaseDevice } from "@/push/register";

/**
 * The scout's own settings: which language, and the way out.
 *
 * These used to live in the header of the work list, where sign-out sat one
 * mis-tap away from the rows a scout taps all day. Everything here is
 * deliberate and rarely used, which is why it has a tab of its own rather
 * than a corner of a screen that is used constantly.
 *
 * **Choosing a farm used to live here too, and should not have.** A farm is
 * not a preference — it is where the work is. Picking one in a settings screen
 * made every other farm's work invisible until the scout came back and changed
 * it, and nothing on the Tasks tab said that was happening. The farms are now
 * the outer grouping of the work itself, so this screen only *states* them:
 * which farms this person holds, and in what role.
 */
export function MeScreen({
  lang,
  onLangChange,
  name,
  farms,
  farmName,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  farms: FarmScope[];
  /** Id -> the name people call it, falling back to the id when unknown. */
  farmName: (farmId: string) => string;
}): ReactNode {
  const [signingOut, setSigningOut] = useState(false);

  return (
    <div className="screen me">
      <h1>{name || t(lang, "me.title")}</h1>

      {/* Read-only. The rows are not buttons and must not look like them: a
          control here that changed what the Tasks tab showed is exactly the
          thing that was wrong with this screen. */}
      <h2 className="section">{farms.length === 1 ? t(lang, "me.farm") : t(lang, "me.farms")}</h2>
      <ul className="farms">
        {farms.map((f) => (
          <li key={f.farm_id} className="static">
            <span className="fname" dir="auto">{farmName(f.farm_id)}</span>
            <span className="role">{f.role}</span>
          </li>
        ))}
      </ul>
      {farms.length > 1 ? <p className="hint">{t(lang, "me.farmsHint")}</p> : null}

      <h2 className="section">{t(lang, "signIn.language")}</h2>
      <div className="langpick">
        {LANGS.map((code) => (
          <button
            key={code}
            type="button"
            className={`lang${code === lang ? " on" : ""}`}
            onClick={() => {
              chooseLang(code);
              onLangChange(code);
            }}
          >
            {LOCALES[code].endonym}
          </button>
        ))}
      </div>

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
          // access token, so clearing the session or reloading before it lands
          // would cancel it and leave this handset receiving a departed
          // scout's visits.
          void releaseDevice().finally(() => {
            signOut();
            location.reload();
          });
        }}
      >
        {t(lang, signingOut ? "visits.signingOut" : "visits.signOut")}
      </button>
    </div>
  );
}
