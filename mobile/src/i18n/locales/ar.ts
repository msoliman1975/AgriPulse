/**
 * Arabic — the language of the person holding the phone.
 *
 * Typed as `Messages`, so this file must stay complete: a key added to `en.ts`
 * fails the build here until it is translated.
 */

import type { Messages } from "@/i18n/types";

export const ar: Messages = {
  "signIn.title": "أجريبالس سكاوت",
  "signIn.subtitle": "سجّل الدخول برقم هاتفك",
  "signIn.phone": "رقم الهاتف",
  "signIn.pin": "الرقم السري (٦ أرقام)",
  "signIn.submit": "دخول",
  "signIn.working": "جارٍ الدخول…",
  "signIn.invalidCredentials": "رقم الهاتف أو الرقم السري غير صحيح",
  "signIn.language": "اللغة",

  "visits.title": "زياراتي",
  "visits.overdue": "متأخرة",
  "visits.assigned": "مُسندة إليّ",
  "visits.claimable": "متاحة",
  "work.board": "أعمال مجدولة",
  "visits.empty": "لا توجد زيارات الآن.",
  "visits.loadFailed": "تعذّر تحميل الزيارات.",
  "visits.claim": "أتولى المهمة",
  "visits.signOut": "خروج",
  "visits.signingOut": "جارٍ الخروج…",
  "farms.none": "لم يتم تعيينك إلى مزرعة بعد. اطلب من المشرف إضافتك.",
  "farms.loading": "جارٍ التحميل…",
  "farms.pick": "اختر المزرعة",

  "due.overdue": "متأخرة",

  "health.checking": "جارٍ فحص الاتصال…",
  "health.ok": "متصل",
  "health.apiDown": "تعذّر الوصول إلى الخادم",
  "health.authDown": "تعذّر الوصول إلى خدمة الدخول",
  "health.bothDown": "لا يوجد اتصال",
  "health.retry": "إعادة المحاولة",
};
