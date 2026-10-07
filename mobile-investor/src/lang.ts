import { Preferences } from "@capacitor/preferences";

import { isLang, type Lang } from "@/i18n";

const LANG_KEY = "agripulse.investor.lang";

/** The language the investor chose, or null if never chosen. */
export async function storedLang(): Promise<Lang | null> {
  const { value } = await Preferences.get({ key: LANG_KEY });
  return isLang(value) ? value : null;
}

export async function storeLang(lang: Lang): Promise<void> {
  await Preferences.set({ key: LANG_KEY, value: lang });
}
