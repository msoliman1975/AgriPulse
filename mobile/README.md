# AgriPulse Scout (Android)

Capacitor + React. `pnpm dev` runs the web build on :5174 alongside the web app
on :5173, so the dispatch→receive loop can be exercised in one sitting.

```
pnpm install
pnpm dev              # browser, no push
pnpm build && npx cap sync android
npx cap open android  # Android Studio
```

## What is still needed to make a phone actually ring

The app registers its FCM token after sign-in and on every cold start, and the
backend has the push channel, device registry, templates and the
visit-assignment notification. None of that has ever delivered to a handset,
because three things are missing and only you can supply them:

1. **A Firebase project** for `cloud.agripulse.scout`, and its
   `android/app/google-services.json`. Git-ignored — it identifies the project,
   so it does not belong in the repo.
2. **Server credentials**: `FCM_ENABLED=true`, `FCM_PROJECT_ID`, and
   `FCM_ACCESS_TOKEN` (an OAuth2 bearer minted from the service account; short
   lived, so production mints it at deploy rather than storing it). Until
   `FCM_ENABLED` is true every send records `status='skipped'` — by design, so a
   dev environment without Firebase does not look like an outage.
3. **A build toolchain and a device.** Capacitor 8 needs **JDK 17+** (this
   machine has 1.8) and the Android SDK on `ANDROID_HOME`.

## Proving it, once those exist

```bash
# 1. enrol a scout and note the PIN
POST /api/v1/users/field-enrolment {phone, full_name, farm_id, role: "Scout"}

# 2. sign in on the handset -> the app registers its token
GET  /api/v1/devices          # should list one device for that user

# 3. dispatch a visit to that scout from the web app (or):
POST /api/v1/scouting/visits:dispatch?farm_id=... {block_id, instruction, assigned_to}

# 4. the phone should show "زيارة فحص — خلال 24h"
SELECT status, error, recipient_address FROM notification_dispatches
 WHERE visit_id = '<id>';     -- 'sent' per device, or the reason it was not
```

Step 4 is the real test: `status='sent'` with no error means the whole chain —
enrolment, token registration, dispatch, template render, FCM — works. Anything
else, the `error` column says which link failed.
