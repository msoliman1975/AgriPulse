# AgriPulse Investor (Android)

The read-only app for investors: their holdings, each holding on a satellite
map, and its details. Phase 3 of `docs/proposals/investor-holdings-design.html`.
Capacitor 8 + React 18 + Vite, the same stack as Scout (`mobile/`).

App id `cloud.agripulse.investor`. Version in three places, kept equal:
`package.json`, `src/version.ts`, `android/app/build.gradle` (`versionName`).

## Build a debug APK

```bash
pnpm install
INVESTOR_ENV=production pnpm build
INVESTOR_ENV=production pnpm exec cap sync android
cd android
JAVA_HOME="C:/Program Files/Eclipse Adoptium/jdk-21.0.9.10-hotspot" ./gradlew assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
```

`INVESTOR_ENV=production` must be set for both `pnpm build` and `cap sync`.
The Capacitor CLI bakes `capacitor.config.ts` into the APK and does not read
`.env` files.

Use JDK 21. Gradle 8.14 does not run on JDK 25, which is the JDK Android
Studio ships; the build then fails with "Unsupported class file major
version 69".

The APK is signed with Gradle's debug key, by decision for the pilot. A debug
APK built on another machine cannot update one built here: the investor has
to uninstall first. A release keystore fixes that; see Scout's README.

## Sign-in

Keycloak's own login page opens in the system browser, with PKCE (S256).
Investors use the email and password from their invitation, and Keycloak
gives them "Forgot password" without app code.

The return trip uses the web client, `agripulse-api`, because a dedicated
`agripulse-investor` client does not exist in production yet:

1. The app opens `/protocol/openid-connect/auth` with
   `redirect_uri=https://app.agripulse.cloud/investor-app/callback`.
2. That web page (`InvestorAppCallbackPage`) sends `code` and `state` to
   `cloud.agripulse.investor://callback`, the link in `AndroidManifest.xml`.
3. The app checks `state`, then trades the code and its verifier for tokens.

The code is useless without the verifier, which never leaves the install.
Token calls use `CapacitorHttp` (native HTTP), because the web client does
not allow this app's origin for CORS at Keycloak's token endpoint.

To move to a dedicated client later: create `agripulse-investor` (public,
PKCE S256, redirect `cloud.agripulse.investor://callback`, the same audience
and `tenant_id` / `tenant_role` / `farm_scopes` mappers as `agripulse-api`),
then change `VITE_KEYCLOAK_CLIENT_ID` and `VITE_KEYCLOAK_REDIRECT_URI` in
`.env.production`.

A token whose `tenant_role` is not `Investor` gets a "this app is for
investors" screen and a sign-out button.

## What the app stores

In Capacitor Preferences (the app's private storage): the session tokens, the
chosen language, and the last `/investor/me` and `/investor/holdings`
answers. With no network the app opens on those and says when they are from.

## Not built yet

- Updates and Harvest tabs, the inbox and push (design phases 4 and 5).
- The company logo (no logo field exists).
- A download link for the update check: `INVESTOR_APP_DOWNLOAD_URL` on the
  api is empty until a download place is chosen.
- Map tiles are not cached for offline use.
