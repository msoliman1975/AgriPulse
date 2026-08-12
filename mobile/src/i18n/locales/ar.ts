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
  "work.back": "رجوع",
  "work.accept": "قبول",
  "work.start": "وصلت — ابدأ",
  "work.record": "سجّل ما تراه",
  "work.what": "ماذا",
  "work.value": "القيمة",
  "work.notes": "ملاحظات",
  "work.save": "حفظ القراءة",
  "work.saving": "جارٍ الحفظ…",
  "work.done": "انتهيت من التسجيل",
  "work.summary": "ملخص للمكتب",
  "work.outcome.resolved": "تم الحل",
  "work.outcome.inconclusive": "لا شيء مؤكد",
  "work.outcome.blocked": "تعذّر التنفيذ",
  "work.recordedCount": "القراءات المحفوظة:",
  "work.alreadyClosed": "هذه المهمة مغلقة.",
  "work.markDone": "تم الإنجاز",
  "work.markSkipped": "لم يكن مطلوبًا",
  "work.actionFailed": "لم تتم العملية. حاول مرة أخرى.",
  "work.recordFailed": "تعذّر حفظ القراءة.",
  "work.loadDefsFailed": "تعذّر تحميل ما يمكن تسجيله.",
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
