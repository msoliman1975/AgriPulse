import { useState, type ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { signOut } from "@/auth/session";
import { LANGS, LOCALES, t, type Lang } from "@/i18n";
import { chooseLang, resetLangOnSignOut } from "@/i18n/preference";
import { releaseDevice } from "@/push/register";

/**
 * The scout's own settings: which farm, which language, and the way out.
 *
 * These used to live in the header of the work list, where sign-out sat one
 * mis-tap away from the rows a scout taps all day. Everything here is
 * deliberate and rarely used, which is why it has a tab of its own rather
 * than a corner of a screen that is used constantly.
 */
export function MeScreen({
  lang,
  onLangChange,
  name,
  farms,
  farmId,
  farmName,
  onPickFarm,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  farms: FarmScope[];
  farmId: string;
  /** Id -> the name people call it, falling back to the id when unknown. */
  farmName: (farmId: string) => string;
  onPickFarm: (farmId: string) => void;
}): ReactNode {
  const [signingOut, setSigningOut] = useState(false);
  const current = farms.find((f) => f.farm_id === farmId);

  return (
    <div className="screen me">
      <h1>{name || t(lang, "me.title")}</h1>
      {/* Role and farm together: "Scout" alone never said *where*, which is
          the half a scout on two farms actually needs. */}
      {current ? (
        <p className="hint">
          {current.role} · {farmName(current.farm_id)}
        </p>
      ) : null}

      {/* Only shown when there is a choice to make. A single-farm scout does
          not need to be told which farm they are on twice. */}
      {farms.length > 1 ? (
        <>
          <h2 className="section">{t(lang, "me.farm")}</h2>
          <ul className="farms">
            {farms.map((f) => (
              <li key={f.farm_id}>
                <button
                  type="button"
                  className={f.farm_id === farmId ? "on" : ""}
                  onClick={() => onPickFarm(f.farm_id)}
                >
                  <span className="fname">{farmName(f.farm_id)}</span>
                  <span className="role">{f.role}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

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
