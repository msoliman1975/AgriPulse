import { useState, type ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { signOut } from "@/auth/session";
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
            void releaseDevice().finally(() => {
              signOut();
              location.reload();
            });
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
