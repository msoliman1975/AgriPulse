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
3. **A device.** The toolchain and release signing both work — see
   "Building an APK" below.

## Building an APK

This needs Android Studio, or the SDK and a JDK 21 or newer. `java -version` on
PATH may report something too old, so point Gradle at Android Studio's own JDK
with `JAVA_HOME`:

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

### Release APK (installs over the previous one)

Android installs an update in place only when the new APK is signed with the
**same key** and has a **higher `versionCode`**. Both are handled:

- **Key**: `app/build.gradle` signs `release` from `android/keystore.properties`
  (git-ignored; copy `keystore.properties.example`) or from the env vars
  `SCOUT_KEYSTORE_FILE`, `SCOUT_KEYSTORE_PASSWORD`, `SCOUT_KEY_ALIAS`,
  `SCOUT_KEY_PASSWORD`. Without either, `assembleRelease` fails with a message
  rather than producing an unsigned APK that will not install.
- **versionCode**: minutes since 2025-01-01 UTC, so every build is higher than
  the last. Not a git commit count — cloud/CI clones are shallow and the count
  would go down. Override with `-PscoutVersionCode=N`.
- **versionName**: set by hand in `app/build.gradle` (currently `1.1`).

```bash
SCOUT_ENV=production pnpm build && SCOUT_ENV=production pnpm exec cap sync android
cd android && ./gradlew assembleRelease
# -> app/build/outputs/apk/release/app-release.apk
```

The release keystore (`agripulse-scout-release.p12`, alias `agripulse-scout`)
was created 2026-11-05 and is held outside the repo by the project owner.
**Back it up. If it is lost, no future build can update installed apps**: every
scout would have to uninstall and reinstall. A phone that has a *debug* build
installed must uninstall it once before the first release build goes on.

CI builds a debug APK on every PR from the production settings, so the native
code is always compiled. It is attached to the `mobile` job as
`scout-debug-apk`. The same limit applies: it is for testing, not for farms.

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
