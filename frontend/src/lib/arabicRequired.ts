/**
 * D26 "Arabic everywhere": the client-side twin of
 * `backend/app/shared/arabic_required.py`.
 *
 * Platform content is saved with Arabic beside every English text, and the
 * API refuses a save that breaks that with a 422 naming each field. The forms
 * check the same rule first so the author sees the message beside the input
 * instead of after a round trip.
 *
 * The rule is the server's, including its backward-compatible half: an
 * existing record whose English text this edit leaves untouched may stay
 * English-only (seeded content without Arabic still saves). Only English that
 * is new, or changed, or whose Arabic is being cleared, needs Arabic.
 */

function blank(value: string | null | undefined): boolean {
  return (value ?? "").trim() === "";
}

/**
 * True when this save would leave English text without the Arabic it needs.
 *
 * `original` is the stored record's pair, or omitted for a new record.
 */
export function needsArabic(
  en: string | null | undefined,
  ar: string | null | undefined,
  original?: { en: string | null | undefined; ar: string | null | undefined } | null,
): boolean {
  if (blank(en) || !blank(ar)) return false;
  if (!original) return true;
  if ((en ?? "").trim() !== (original.en ?? "").trim()) return true;
  return !blank(original.ar);
}
