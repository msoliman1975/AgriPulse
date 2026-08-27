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
  "work.takeMeThere": "Take me there",
  "work.noLocation": "No location saved for this job",
  "work.atCellCentre": "This points at the centre of the zone.",
  "work.atBlockCentre": "This points at the centre of the block.",
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

  "tab.tasks": "Tasks",
  "tab.records": "Records",

  // The farm rail: one control, on every farm-scoped screen. `rail.label`
  // is never drawn — it names the control for a screen reader, which
  // otherwise announces a row of farm names with no idea what they do.
  "rail.label": "Which farm",
  "rail.allFarms": "All farms",
  "rail.failed": "This farm did not answer",

  "seg.mine": "My work",
  "seg.available": "Available",
  "seg.done": "Done",

  "bucket.overdue": "Overdue",
  "bucket.today": "Today",
  "bucket.week": "This week",
  "bucket.next": "Next week",
  "bucket.later": "Later",
  // Finished work is grouped by the day it was closed, not by a deadline it
  // can no longer miss, so it needs buckets that point backwards.
  "bucket.doneToday": "Today",
  "bucket.doneWeek": "This week",
  "bucket.doneEarlier": "Earlier",
  "bucket.doneUnknown": "No date",

  "group.byBlock": "By block",
  "group.byDue": "By time",
  "group.noBlock": "No block",
  // "All farms" is an overview, not a gate. Named for the question it
  // answers rather than for what it lists.
  "group.farmsStart": "Where the day starts",
  "group.farmsDone": "What you closed",

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
  "record.whichFarm": "Which farm?",
  // The farm is inherited from the rail and stated, not asked. It is only
  // asked outright when the rail is on "All farms", which is the one time
  // the app genuinely does not know.
  "record.filingTo": "Filing to",
  "record.changeFarm": "Change",
  "record.pickFarm": "Choose a farm",
  "record.farmFirst": "Choose a farm first",
  "record.whichBlock": "Which block?",
  "record.start": "Start",
  "record.noBlocks": "This farm has no blocks.",
  "record.blocksFailed": "Could not load the blocks.",
  "record.roundFailed": "Could not start the round.",

  "home.greeting": "Signed in as",
  "work.needValue": "Choose a value before saving.",
  // The lookup list and the bounds the tenant defined for this signal. The
  // server rejects anything outside them, so these say what to change rather
  // than reporting a refusal after the fact. `{min}`, `{max}` and `{allowed}`
  // are filled in by CaptureForm.
  "work.needNumber": "Enter a number.",
  "work.belowMin": "Too low. The smallest allowed is {min}.",
  "work.aboveMax": "Too high. The largest allowed is {max}.",
  "work.notAllowed": "Choose one of: {allowed}",
  "work.range": "Allowed:",
  "work.needPosition": "Set your position first — it is the reading.",
  "work.positionIsValue": "Your position will be saved as the reading.",
  "work.unknownKind": "This signal cannot be recorded on the phone. Tell the office.",
  "work.whatHappened": "What happened",
  "work.optional": "Optional",
  "work.yes": "Yes",
  "work.no": "No",

  "flag.title": "Flag something",
  "flag.howSerious": "How serious?",
  "flag.severityHint": "This sets the colour of the pin your supervisor sees.",
  "flag.sev.info": "Worth knowing",
  "flag.sev.warning": "Needs attention",
  "flag.sev.critical": "Urgent",
  "flag.whatDidYouSee": "What did you see?",
  "flag.raise": "Raise flag",
  "flag.needNote": "Say what you saw before raising it.",
  "flag.raiseFailed": "Could not raise that flag.",
  "flag.open": "Open",
  "flag.closed": "Closed",
  "flag.unpinned": "No longer shown on the map, but still open.",
  "flag.outcome": "How it was closed",
  "flag.reason.actioned": "Actioned",
  "flag.reason.noAction": "No action needed",
  "flag.reason.duplicate": "Already reported",
  "flag.kind.close": "closed it",
  "flag.kind.reopen": "re-opened it",
  "flag.someone": "Someone",
  "flag.reply": "Send reply",
  "flag.reopen": "It is still there",
  "flag.replyPlaceholder": "Write a reply…",
  "flag.needReply": "Write something first.",
  "flag.replyFailed": "That did not go through.",
  "flag.loadFailed": "Could not load that flag.",
  "flag.chooser": "Flag something I saw",
  "flag.chooserHint": "Unexpected, and somebody else needs to deal with it.",

  "tasks.someFarmsFailed": "Some farms could not be loaded. Pull down and retry.",

  "records.title": "My records",
  "records.empty": "You have not recorded anything in the last 30 days.",
  "records.loadFailed": "Could not load your records.",

  "me.title": "My account",
  "me.farm": "Farm",
  // Read-only. Choosing a farm happens where the work is — on the rail at
  // the top of the list — rather than in a settings screen two taps away.
  // The hints say what this list is NOT, which is the thing a scout who
  // remembers the old settings screen will assume it still is.
  "me.farms": "Your farms",
  "me.farmsHint": "Your role on each. Switch farms on the rail above your work.",
  "me.roleHint": "Your role on this farm.",
  "me.close": "Close",

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

  "refresh.pull": "Pull down to update",
  "refresh.release": "Let go to update",
  "refresh.working": "Updating…",
} as const;
