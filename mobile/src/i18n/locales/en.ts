/**
 * English — the canonical catalogue.
 *
 * Every other locale is typed against this one, so adding a key here and
 * forgetting to translate it is a build error rather than a raw key on a
 * scout's screen. That has shipped to production in the web app before.
 */

export const en = {
  "signIn.title": "AgriPulse Scout",
  "signIn.subtitle": "Sign in with your phone number",
  "signIn.phone": "Phone number",
  "signIn.pin": "6-digit PIN",
  "signIn.submit": "Sign in",
  "signIn.working": "Signing in…",
  "signIn.invalidCredentials": "That phone number or PIN is not right",
  "signIn.language": "Language",

  "visits.title": "My visits",
  "visits.overdue": "Overdue",
  "visits.assigned": "Assigned to me",
  "visits.claimable": "Open to claim",
  "work.board": "Scheduled work",
  "visits.empty": "Nothing to walk right now.",
  "visits.loadFailed": "Could not load your visits.",
  "visits.claim": "I'll take it",
  "visits.signOut": "Sign out",
  "visits.signingOut": "Signing out…",
  "farms.none": "You are not assigned to a farm yet. Ask your supervisor to add you.",
  "farms.loading": "Loading…",
  "farms.pick": "Choose a farm",

  "due.overdue": "overdue",

  // Reachability. Shown before sign-in, because "wrong PIN" and "the server is
  // not there" look identical from the sign-in screen otherwise.
  "health.checking": "Checking connection…",
  "health.ok": "Connected",
  "health.apiDown": "Cannot reach the server",
  "health.authDown": "Cannot reach sign-in",
  "health.bothDown": "No connection",
  "health.retry": "Retry",
} as const;
