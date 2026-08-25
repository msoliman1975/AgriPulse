import type { ReactNode } from "react";

import { LANGS, LOCALES, t, type Lang } from "@/i18n";
import { chooseLang } from "@/i18n/preference";

/**
 * Who is holding the phone, and which language it speaks.
 *
 * Both used to live only on the Me tab. A handset is passed between people at
 * shift change, and a scout who does not read the language the app opened in
 * cannot navigate to a screen called "Me" to change it — the switch has to be
 * on the first screen, in each language's own name. The name is here for the
 * same reason: it is how somebody notices the phone is still signed in as the
 * scout who had it yesterday.
 *
 * The farm sits under the name for the third version of that problem: a scout
 * who works two farms had no way to tell, from the screen they spend the day
 * on, which one's work they were looking at.
 */
export function HomeHeader({
  lang,
  onLangChange,
  name,
  farmName,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  farmName: string | null;
}): ReactNode {
  return (
    <header className="homehead">
      <div className="who">
        <span className="lbl">{t(lang, "home.greeting")}</span>
        <span className="nm" dir="auto">{name ?? "—"}</span>
        {farmName ? <span className="farm" dir="auto">{farmName}</span> : null}
      </div>
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
    </header>
  );
}
