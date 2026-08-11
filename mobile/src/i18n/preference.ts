/**
 * Which language this handset shows, and who gets to decide.
 *
 * Two sources, and the precedence between them is the whole design:
 *
 * * **The person's own choice on this device wins, permanently.** Somebody who
 *   taps "English" on the sign-in screen has told us something the server does
 *   not know, and having the next sign-in silently undo it is the kind of thing
 *   that makes an app feel broken.
 * * **Otherwise the server's per-user default applies** (`user_preferences.language`,
 *   set at enrolment and editable by a supervisor). This is what "set the
 *   default language on a team member" means in practice: it lands on the
 *   phone of somebody who has never expressed a preference.
 *
 * The sign-in screen has to be readable *before* any of the server's opinion is
 * available, so the pre-auth choice falls back to the device's own language and
 * then to Arabic.
 */

import { DEFAULT_LANG, isLang, type Lang } from "@/i18n";

const CHOICE_KEY = "agripulse.scout.lang";
const EXPLICIT_KEY = "agripulse.scout.lang.explicit";

/** Swap-point for `@capacitor/preferences`, same as the session store. */
const storage = {
  read(key: string): string | null {
    return localStorage.getItem(key);
  },
  write(key: string, value: string | null): void {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  },
};

function fromDevice(): Lang | null {
  // `navigator.language` is "ar-EG" on a phone set to Egyptian Arabic; only the
  // primary subtag is meaningful to us.
  const primary = (navigator.language || "").split("-")[0];
  return isLang(primary) ? primary : null;
}

/** What to render with before anything is known about the user. */
export function initialLang(): Lang {
  const stored = storage.read(CHOICE_KEY);
  if (isLang(stored)) return stored;
  const env = import.meta.env.VITE_LANG;
  if (isLang(env)) return env;
  return fromDevice() ?? DEFAULT_LANG;
}

/** The user tapped a language. Remembered, and never overridden afterwards. */
export function chooseLang(lang: Lang): void {
  storage.write(CHOICE_KEY, lang);
  storage.write(EXPLICIT_KEY, "1");
}

export function hasExplicitChoice(): boolean {
  return storage.read(EXPLICIT_KEY) === "1";
}

/**
 * Adopt the server's default for this person. Returns the language now in
 * effect, so the caller can re-render without re-reading storage.
 */
export function adoptServerLang(lang: Lang): Lang {
  if (hasExplicitChoice()) return initialLang();
  storage.write(CHOICE_KEY, lang);
  return lang;
}

/**
 * Sign-out clears the *implicit* language but keeps an explicit one: the next
 * scout on a shared handset should get their own default, while a device that
 * has been deliberately set to English stays English.
 */
export function resetLangOnSignOut(): void {
  if (!hasExplicitChoice()) storage.write(CHOICE_KEY, null);
}
