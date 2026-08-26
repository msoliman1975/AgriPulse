import type { ReactNode } from "react";

import { LANGS, LOCALES, t, type Lang } from "@/i18n";
import { chooseLang } from "@/i18n/preference";

/**
 * Who is holding the phone, which language it speaks, and the way out.
 *
 * Both the name and the language used to live only on a "Me" tab. A handset is
 * passed between people at shift change, and a scout who does not read the
 * language the app opened in cannot navigate to a screen called "Me" to change
 * it — the switch has to be on the first screen, in each language's own name.
 * The name is here for the same reason: it is how somebody notices the phone is
 * still signed in as the scout who had it yesterday.
 *
 * **The name is now also the door.** The Me tab is gone: the farm rail states
 * the farms, this header states the language, and what was left was one thing —
 * signing out. That did not deserve a third of the tab bar, but it also cannot
 * sit loose in this header, which is why the Me tab existed in the first place:
 * a mis-tap beside the rows a scout taps all day signs them out standing in a
 * field. So it lives one deliberate tap in, behind the name.
 *
 * The farm sits under the name only for a scout who holds exactly one. More
 * than one is a question the rail below is already asking, and answering it up
 * here too would name a farm the list is not limited to.
 */
export function HomeHeader({
  lang,
  onLangChange,
  name,
  farmName,
  onOpenAccount,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  /** The one farm's name, or null when the rail is carrying that job. */
  farmName: string | null;
  onOpenAccount: () => void;
}): ReactNode {
  return (
    <header className="homehead">
      <button type="button" className="who" onClick={onOpenAccount}>
        <span className="txt">
          <span className="lbl">{t(lang, "home.greeting")}</span>
          <span className="nm" dir="auto">
            {name ?? "—"}
          </span>
          {farmName ? (
            <span className="farm" dir="auto">
              {farmName}
            </span>
          ) : null}
        </span>
        {/* Chevron, not a gear or an avatar: it says "there is more of this
            here", which is exactly what is behind it — more about this person.
            Drawn rather than a glyph so it inherits the muted colour and
            mirrors nothing under RTL, where a down chevron is still down. */}
        <svg className="chev" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="m6 9 6 6 6-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
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
