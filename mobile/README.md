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
3. **A device, and a signing key.** The toolchain itself works — see
   "Building an APK" below. What is missing is a keystore, so nothing built
   here can be installed as a release.

## Building an APK

The build works on this machine, checked 2026-08-26. `java -version` on PATH
reports 1.8, which is too old, but Android Studio ships its own JDK 25 and
Gradle takes it from `JAVA_HOME`:

```bash
pnpm install && pnpm build
npx cap sync android
cd android
JAVA_HOME="C:/Program Files/Android/Android Studio/jbr" ./gradlew assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk, about 6.2 MB
```

A **debug** APK is signed with Gradle's generated debug key. It installs on a
handset for testing and is not something to hand to a farm: the debug key is
not stable across machines, so the next build cannot upgrade it in place.

A **release** APK needs a keystore, and there is no `signingConfig` in
`app/build.gradle`. Until one exists, `assembleRelease` produces an unsigned
APK that Android refuses to install. The keystore has to be created once and
kept — losing it means the app can never be updated, only reinstalled under a
new identity.

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
