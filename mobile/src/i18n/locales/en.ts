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

  "tab.tasks": "Tasks",
  "tab.records": "Records",
  "tab.me": "Me",

  "seg.mine": "My work",
  "seg.available": "Available",
  "seg.done": "Done",

  "bucket.overdue": "Overdue",
  "bucket.today": "Today",
  "bucket.week": "This week",
  "bucket.next": "Next week",
  "bucket.later": "Later",

  "group.byBlock": "Group by block",
  "group.byDue": "Group by time",
  "group.noBlock": "No block",

  "empty.mine": "Nothing to walk right now.",
  "empty.available": "Nothing open to take.",
  "empty.done": "Nothing finished yet.",

  "record.fab": "＋ Record",
  "record.title": "Record something",
  "record.round": "Log a round I did",
  "record.roundHint": "You inspected a block on your own. Same form, closes with an outcome.",
  "record.reading": "Enter a reading",
  "record.readingHint": "One measurement — trap count, incidence, soil feel.",
  "record.cancel": "Cancel",
  "record.whichBlock": "Which block?",
  "record.start": "Start",
  "record.noBlocks": "This farm has no blocks.",
  "record.blocksFailed": "Could not load the blocks.",
  "record.roundFailed": "Could not start the round.",

  "home.greeting": "Signed in as",
  "work.needValue": "Choose a value before saving.",
  "work.whatHappened": "What happened",
  "work.optional": "Optional",
  "work.yes": "Yes",
  "work.no": "No",

  "records.title": "My records",
  "records.empty": "You have not recorded anything in the last 30 days.",
  "records.loadFailed": "Could not load your records.",

  "me.title": "My account",
  "me.farm": "Farm",

  "work.why": "Why you are going",
  "work.photos": "Photos",
  "work.takePhoto": "Take photo",
  "work.choosePhoto": "Choose photos",
  "work.removePhoto": "Remove photo",
  "work.uploading": "Uploading",
  "work.positionOff": "Position not set",
  "work.positionSet": "Position set",
  "work.positionUse": "Use my position",
  "work.positionRedo": "Update position",
  "work.positionAsking": "Finding you…",
  "work.positionDenied": "Location permission refused",
  "work.positionUnavailable": "Position not available",

  "due.overdue": "late",

  // Reachability. Shown before sign-in, because "wrong PIN" and "the server is
  // not there" look identical from the sign-in screen otherwise.
  "health.checking": "Checking connection…",
  "health.ok": "Connected",
  "health.apiDown": "Cannot reach the server",
  "health.authDown": "Cannot reach sign-in",
  "health.bothDown": "No connection",
  "health.retry": "Retry",
} as const;
