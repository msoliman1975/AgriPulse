# Setting up Firebase push for AgriPulse Scout

First time with Android? This assumes nothing. Follow it in order — later steps
depend on earlier ones, and a couple of places fail *silently* if skipped, which
is worse than an error.

Everything here happens **once per environment** (dev, prod). About 30 minutes.

---

## Vocabulary, so the screens make sense

| Term | What it actually is |
|---|---|
| **Firebase project** | A Google project that owns your push credentials. Free. |
| **FCM** | Firebase Cloud Messaging — the service that carries a push to a phone. |
| **`google-services.json`** | Config the *app* needs so it can ask FCM for a token. Goes in the repo tree, git-ignored. |
| **Service account** | A robot Google account the *server* uses to send pushes. |
| **Package name / applicationId** | Your app's unique id: **`cloud.agripulse.scout`**. Must match everywhere. |

The flow, once set up: the app asks FCM for a **device token** → sends it to our
backend (`POST /devices:register`) → when a visit is assigned, the backend asks
FCM to deliver to that token.

---

## Part 1 — Create the Firebase project

1. Go to <https://console.firebase.google.com> and sign in.
2. **Create a project** → name it `agripulse` (or `agripulse-dev`).
3. Google Analytics: **turn it off**. It adds consent and data-residency
   questions you do not need for push, and you can enable it later.
4. Wait for "Your new project is ready" → **Continue**.

## Part 2 — Register the Android app

1. On the project home, click the **Android** icon ("Add app").
2. **Android package name**: `cloud.agripulse.scout`

   > ⚠️ This must match `appId` in `mobile/capacitor.config.ts` **exactly**.
   > A mismatch does not error — the app simply never receives a push, and
   > nothing tells you why. If you ever change one, change both.

3. **App nickname**: `AgriPulse Scout` (cosmetic).
4. **Debug signing certificate SHA-1**: leave blank. It is only needed for
   Google Sign-In and Dynamic Links; FCM does not use it.
5. **Register app** → **Download `google-services.json`**.
6. Put the file at exactly:

   ```
   mobile/android/app/google-services.json
   ```

   It is already git-ignored — it identifies your project, so each environment
   supplies its own.

7. Skip the "Add Firebase SDK" and "Next steps" screens in the console —
   Capacitor already provides the SDK, and Part 3 confirms the wiring is done.

## Part 3 — Gradle wiring (already done — just verify)

Most FCM tutorials tell you to edit two `build.gradle` files. **Capacitor 8 has
already done it**, so you should change nothing here. Verified in this repo:

* `android/build.gradle` already carries
  `classpath 'com.google.gms:google-services:4.4.4'`
* `android/app/build.gradle` ends with a block that applies the plugin **only if
  `google-services.json` exists**, and otherwise logs:

  ```
  google-services.json not found, google-services plugin not applied.
  Push Notifications won't work
  ```

That log line is your friend: if you see it during a build, the file is missing
or in the wrong folder. Check it is at `mobile/android/app/google-services.json`
— *inside* `app/`, not next to it.

## Part 4 — Server credentials

The backend sends pushes through the **FCM v1 API**, which authenticates with a
short-lived OAuth2 token minted from a service account. (The old "server key"
you may see in tutorials is the deprecated legacy API — do not use it.)

1. Firebase console → ⚙️ **Project settings** → **Service accounts** tab.
2. **Generate new private key** → confirm → a `.json` file downloads.
3. **Treat this like a password.** It can send pushes to all your users. Do not
   commit it. Keep it outside the repo, e.g. `C:\keys\agripulse-fcm.json`.
4. Note your **Project ID** from the same settings page (e.g. `agripulse-dev`).

## Part 5 — Point the backend at it

`backend/.env` already carries the block below (`FCM_PROJECT_ID` was read out of
your `google-services.json`). You only need to fill in the key file and flip the
switch:

```dotenv
FCM_ENABLED=true
FCM_PROJECT_ID=agripulse-scout
FCM_SERVICE_ACCOUNT_FILE=C:/keys/agripulse-fcm.json
```

Restart the API afterwards — settings are read once at startup.

> The one-hour expiry problem is handled: the backend now loads the service
> account itself and refreshes the bearer when it goes stale, so there is
> nothing to re-mint. `FCM_ACCESS_TOKEN` still exists as an escape hatch for a
> quick test without a key file, and if set it wins — but it stops working after
> an hour, which is exactly why the file is the better path.

## Part 6 — Point the app at the right host

A phone or emulator does not share your laptop's `localhost`. In
`mobile/.env.local`:

```dotenv
# Emulator: 10.0.2.2 is the host machine. Real device: your laptop's LAN IP.
VITE_API_BASE_URL=http://10.0.2.2:8000/api/v1
VITE_KEYCLOAK_ISSUER=http://10.0.2.2:8080/realms/agripulse
VITE_KEYCLOAK_CLIENT_ID=agripulse-mobile
VITE_FARM_ID=<a farm uuid the test scout is scoped to>
VITE_LANG=ar
```

Keycloak must also accept that issuer, or token validation fails. For local dev
the simplest route is to run Keycloak with `KC_HOSTNAME_STRICT=false`.

## Part 7 — Build and install

```bash
# Java 17+ is required. This machine already has it:
setx JAVA_HOME "C:\Program Files\Java\open-jdk-17.0.17.0-win\jdk"
# (open a new terminal afterwards so the change is picked up)

cd mobile
pnpm build
npx cap sync android
npx cap open android      # opens Android Studio; press ▶ to install
```

Android Studio will offer to install the SDK on first run — accept the defaults.

## Part 8 — Prove it end to end

Each step tells you which link failed if it stops here.

```bash
# 1. Enrol a test scout — note the PIN it returns once.
POST /api/v1/users/field-enrolment
     {"phone": "01001234567", "full_name": "Test Scout",
      "farm_id": "<farm>", "role": "Scout"}

# 2. Sign in on the device with that phone + PIN.
#    Allow notifications when Android asks.

# 3. Did the device register?
GET /api/v1/devices          # expect exactly one row
```

If step 3 is empty the app never got an FCM token. In order of likelihood:
the `google-services.json` is in the wrong folder (watch the build log for the
"plugin not applied" line), notifications were denied at the Android prompt, or
the package name in Firebase does not match `cloud.agripulse.scout`.

```bash
# 4. Send the scout a visit.
POST /api/v1/scouting/visits:dispatch?farm_id=<farm>
     {"block_id": "<block>", "instruction": "Walk the north edge",
      "assigned_to": "<the scout's user_id>", "due_within_hours": 24}

# 5. The phone should show:  زيارة فحص — خلال 24h
```

If nothing arrives, the answer is in the database, not the logs:

```sql
SELECT status, error, recipient_address
  FROM notification_dispatches
 WHERE visit_id = '<visit id>';
```

| What you see | What it means |
|---|---|
| `sent`, no error | **It worked.** The whole chain is proven. |
| `skipped` — "push channel disabled" | `FCM_ENABLED` is not true, or the backend was not restarted. |
| `skipped` — "no registered devices" | Step 3 never happened. |
| `skipped` — "user has not enabled push" | That user's `notification_channels` lacks `push`. Enrolment sets it; a hand-made user may not have it. |
| `failed` — 401 / UNAUTHENTICATED | `FCM_ACCESS_TOKEN` expired — see Part 5. |
| `failed` — SenderId mismatch | The app's `google-services.json` belongs to a different Firebase project than `FCM_PROJECT_ID`. |
| no rows at all | The visit was never assigned, so nothing was sent. Check `assigned_to`. |

---

## If you get stuck

Two failures account for most first attempts, and neither produces a red error:

1. **Package-name mismatch.** Firebase registered as something other than
   `cloud.agripulse.scout`. The app builds, signs in, and simply never receives
   a push. If you got it wrong, add a *second* Android app in the same Firebase
   project with the right package name and re-download the JSON — you do not
   need to start over.
2. **`google-services.json` in the wrong folder.** It belongs in
   `mobile/android/app/`, not `mobile/android/`. The build log says so
   explicitly (see Part 3) — read it rather than guessing.

Work the table in Part 8 before anything else. `notification_dispatches` records
what happened for every device, including the reason a push was *not* sent, so
the answer is almost always already written down.
