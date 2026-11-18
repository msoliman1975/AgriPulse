/**
 * A `?returnTo=` value that is safe to navigate to: an in-app path only.
 *
 * Readiness fix links carry the designer's own URL so the user lands back on
 * the list they were fixing. Anything that is not a single-slash path (an
 * absolute URL, `//host`, `javascript:`) is dropped, so the parameter cannot
 * send anyone off the app.
 */
export function safeReturnTo(value: string | null | undefined): string | null {
  if (!value) return null;
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return null;
  return value;
}
