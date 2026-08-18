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
  "work.back": "Back",
  "work.accept": "Accept",
  "work.start": "I'm here — start",
  "work.record": "Record what you see",
  "work.what": "What",
  "work.value": "Value",
  "work.notes": "Notes",
  "work.save": "Save reading",
  "work.saving": "Saving…",
  "work.done": "Done recording",
  "work.summary": "Summary for the office",
  "work.outcome.resolved": "Resolved",
  "work.outcome.inconclusive": "Nothing conclusive",
  "work.outcome.blocked": "Could not do it",
  "work.recordedCount": "Readings saved:",
  "work.alreadyClosed": "This job is closed.",
  "work.markDone": "Mark done",
  "work.markSkipped": "Not needed",
  "work.actionFailed": "That did not go through. Try again.",
  "work.recordFailed": "Could not save that reading.",
  "work.loadDefsFailed": "Could not load what can be recorded.",
  "visits.empty": "Nothing to walk right now.",
  "visits.loadFailed": "Could not load your visits.",
  "visits.claim": "I'll take it",
  // One visit can now stand for several grid cells of one block, and it
  // can have been true for days before anyone walked it. Both change what
  // a scout does on arrival, so both are on the row rather than buried in
  // the detail screen.
  "visits.zones": "{n} zones",
  "visits.zonesOne": "1 zone",
  "visits.daysRunning": "{n} days running",
  // A count with no baseline is not a trend: a scout walking a spreading
  // outbreak needs to know that before they arrive, not after.
  "visits.spreading": "spreading",
  "visits.receding": "receding",
  "visits.sinceYesterday": "since yesterday",
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
