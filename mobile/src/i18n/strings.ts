/**
 * Arabic first, because that is the language of the person holding the phone.
 * A tiny hand-rolled dictionary rather than i18next for now: the app has one
 * screen's worth of copy, and pulling the web app's catalogues in before the
 * screens settle would freeze keys we are still naming.
 */

export type Lang = "ar" | "en";

export const STRINGS = {
  ar: {
    "signIn.title": "أجريبالس سكاوت",
    "signIn.subtitle": "سجّل الدخول برقم هاتفك",
    "signIn.phone": "رقم الهاتف",
    "signIn.pin": "الرقم السري (٦ أرقام)",
    "signIn.submit": "دخول",
    "signIn.working": "جارٍ الدخول…",
    "signIn.invalidCredentials": "رقم الهاتف أو الرقم السري غير صحيح",
    "visits.title": "زياراتي",
    "visits.overdue": "متأخرة",
    "visits.assigned": "مُسندة إليّ",
    "visits.claimable": "متاحة",
    "visits.empty": "لا توجد زيارات الآن.",
    "visits.loadFailed": "تعذّر تحميل الزيارات.",
    "visits.claim": "أتولى المهمة",
    "visits.signOut": "خروج",
    "visits.signingOut": "جارٍ الخروج…",
    "due.overdue": "متأخرة",
  },
  en: {
    "signIn.title": "AgriPulse Scout",
    "signIn.subtitle": "Sign in with your phone number",
    "signIn.phone": "Phone number",
    "signIn.pin": "6-digit PIN",
    "signIn.submit": "Sign in",
    "signIn.working": "Signing in…",
    "signIn.invalidCredentials": "That phone number or PIN is not right",
    "visits.title": "My visits",
    "visits.overdue": "Overdue",
    "visits.assigned": "Assigned to me",
    "visits.claimable": "Open to claim",
    "visits.empty": "Nothing to walk right now.",
    "visits.loadFailed": "Could not load your visits.",
    "visits.claim": "I'll take it",
    "visits.signOut": "Sign out",
    "visits.signingOut": "Signing out…",
    "due.overdue": "overdue",
  },
} as const;

export type StringKey = keyof (typeof STRINGS)["en"];

export function t(lang: Lang, key: StringKey): string {
  return STRINGS[lang][key] ?? STRINGS.en[key];
}

/**
 * "18h" / "2d" / overdue — the countdown the visit ring shows.
 *
 * Rounds rather than floors, for the same reason the push copy does: a visit
 * raised with within_hours=24 is a moment short of 24h by the time it renders,
 * and "23h" reads as if the scout has already lost an hour.
 */
export function dueIn(lang: Lang, dueBy: string | null): string {
  if (!dueBy) return "";
  const ms = new Date(dueBy).getTime() - Date.now();
  if (ms < 0) return t(lang, "due.overdue");
  const hours = Math.round(ms / 3_600_000);
  return hours < 48 ? `${Math.max(hours, 1)}h` : `${Math.round(hours / 24)}d`;
}
