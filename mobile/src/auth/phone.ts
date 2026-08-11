/**
 * Turn what a scout types into the username Keycloak actually holds.
 *
 * Enrolment normalises to E.164 and stores that as the username, because the
 * phone *is* the identity and two spellings would be two accounts. The app was
 * sending the raw input straight through, so only somebody who typed
 * `+201002203402` exactly could sign in — while every Egyptian writes their own
 * number `01002203402`. Keycloak answers `invalid_grant` for an unknown
 * username and for a wrong password alike, so the app reported "wrong phone or
 * PIN" and the scout, holding a correct phone and a correct PIN, had no way to
 * tell what was wrong.
 *
 * Mirrors `backend/app/shared/keycloak/field_identity.normalise_phone`. Keep
 * the two in step: a difference here does not fail loudly, it just refuses a
 * valid sign-in.
 */

/** Default country for a bare local number. Egypt. */
const DEFAULT_CC = "20";

/**
 * Best-effort E.164. Returns the input trimmed when it cannot do better —
 * being wrong here must not stop somebody whose number this function has not
 * anticipated from trying.
 */
export function normalisePhone(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return trimmed;

  // Keep a leading +, drop every other non-digit: spaces, dashes, brackets,
  // and the Arabic-Indic digits a scout's keyboard may produce.
  const western = trimmed.replace(/[٠-٩]/g, (d) =>
    String(d.charCodeAt(0) - 0x0660),
  );
  const plus = western.startsWith("+");
  const digits = western.replace(/\D/g, "");
  if (!digits) return trimmed;

  if (plus) return `+${digits}`;
  // 00 is the other way to write +.
  if (digits.startsWith("00")) return `+${digits.slice(2)}`;
  // A local number: 01xxxxxxxxx -> +20 1xxxxxxxxx.
  if (digits.startsWith("0")) return `+${DEFAULT_CC}${digits.slice(1)}`;
  // Already carries the country code, just without the plus.
  if (digits.startsWith(DEFAULT_CC)) return `+${digits}`;
  return `+${digits}`;
}
